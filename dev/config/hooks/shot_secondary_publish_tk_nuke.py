# Copyright (c) 2013 Shotgun Software Inc.
# 
# CONFIDENTIAL AND PROPRIETARY
# 
# This work is provided "AS IS" and subject to the Shotgun Pipeline Toolkit 
# Source Code License included in this distribution package. See LICENSE.
# By accessing, using, copying or modifying this work you indicate your 
# agreement to the Shotgun Pipeline Toolkit Source Code License. All rights 
# not expressly granted therein are reserved by Shotgun Software Inc.

import os
import shutil
import sys

import nuke

import sgtk
import tank
from tank import Hook
from tank import TankError

sys.path.append('K:/')
import CodeRepo.Deadline.utils as cdu
reload(cdu)

class PublishHook(Hook):
    """
    Single hook that implements publish functionality for secondary tasks
    """
            
    def execute(self, tasks, work_template, comment, thumbnail_path, sg_task, primary_publish_path, progress_cb, **kwargs):
        """
        Main hook entry point
        :tasks:         List of secondary tasks to be published.  Each task is a 
                        dictionary containing the following keys:
                        {
                            item:   Dictionary
                                    This is the item returned by the scan hook 
                                    {   
                                        name:           String
                                        description:    String
                                        type:           String
                                        other_params:   Dictionary
                                    }
                                   
                            output: Dictionary
                                    This is the output as defined in the configuration - the 
                                    primary output will always be named 'primary' 
                                    {
                                        name:             String
                                        publish_template: template
                                        tank_type:        String
                                    }
                        }
                        
        :work_template: template
                        This is the template defined in the config that
                        represents the current work file
               
        :comment:       String
                        The comment provided for the publish
                        
        :thumbnail:     Path string
                        The default thumbnail provided for the publish
                        
        :sg_task:       Dictionary (shotgun entity description)
                        The shotgun task to use for the publish               
                     
        :primary_publish_path: Path string
                        This is the path of the primary published file as returned
                        by the primary publish hook                     
                        
        :progress_cb:   Function
                        A progress callback to log progress during pre-publish.  Call:
                        
                            progress_cb(percentage, msg)
                             
                        to report progress to the UI
        
        :returns:       A list of any tasks that had problems that need to be reported 
                        in the UI.  Each item in the list should be a dictionary containing 
                        the following keys:
                        {
                            task:   Dictionary
                                    This is the task that was passed into the hook and
                                    should not be modified
                                    {
                                        item:...
                                        output:...
                                    }
                                    
                            errors: List
                                    A list of error messages (strings) to report    
                        }
        """
        results = []
            
        # we will need the write node app if we have any render outputs to validate
        write_node_app = self.parent.engine.apps.get("tk-nuke-writenode")
        if not write_node_app:
            raise TankError("Unable to validate write node without tk-nuke-writenode app!")
                
        # Keep of track of what has been published in shotgun
        # this is needed as input into the review creation code...
        render_publishes = {}
        
        # process tasks:
        for task in tasks:
            
            item = task["item"]
            output = task["output"]
            
            # keep track of our errors for this task
            errors = []
            
            # the output name is 'render' or 'quicktime' in our std setup.
            output_name = task["output"]["name"]
            
            # each publish task is connected to a nuke write node
            # this value was populated via the scan scene hook
            write_node = task["item"].get("other_params", dict()).get("node")
            if not write_node:
                raise TankError("Could not determine nuke write node for item '%s'!" % str(task))
            
            # report progress:
            progress_cb(0.0, "Publishing", task)
        
            # depending on output type:
            if output_name == "render":

                # publish write-node rendered sequence                
                try:
                    (sg_publish, thumbnail_path) = self._publish_write_node_render(task, 
                                                                                   write_node, 
                                                                                   write_node_app, 
                                                                                   primary_publish_path, 
                                                                                   sg_task, 
                                                                                   comment, 
                                                                                   progress_cb)
                    
                    # keep track of our publish data so that we can pick it up later in review
                    render_publishes[ write_node.name() ] = (sg_publish, thumbnail_path)
                except Exception, e:
                    errors.append("Publish failed - %s" % e)
            
            elif output_name == "quicktime":
                # Submit published sequence to Screening Room
                try:
                    
                    # If we have the tk-multi-reviewsubmission app we can create versions
                    review_submission_app = self.parent.engine.apps.get("tk-multi-reviewsubmission")

                    if not review_submission_app:
                        self.parent.log_warning("The Review Submission app can not be found. "
                                                "Shotgun Versions will not be automatically created.")
                    
                    else:
                        
                        # pick up sg data from the render dict we are maintianing
                        # note: we assume that the rendering tasks always happen
                        # before the review tasks inside the publish... 
                        (sg_publish, thumbnail_path) = render_publishes[ write_node.name() ]
                        
                        self._send_to_screening_room(
                            write_node,
                            write_node_app,
                            review_submission_app,
                            sg_publish,
                            sg_task,
                            comment,
                            thumbnail_path,
                            progress_cb
                        )

                except Exception, e:
                    errors.append("Submit to Screening Room failed - %s" % e)
            
            #render local---
            elif output_name == 'render_local':
                
                #rendering---
                #getting write node
                write_node = item.get("other_params", dict()).get("node")
                
                #getting frame range
                firstframe=nuke.toNode( "root" )['first_frame'].value()
                lastframe=nuke.toNode( "root" )['last_frame'].value()
                
                #render write node
                nuke.execute(write_node,int(firstframe),int(lastframe),1)
                
                #validate renders---
                # validate that the write node has rendered images to publish:
                # ...
                if not write_node_app:
                    errors.append("Unable to validate write node '%s' without tk-nuke-writenode app!" % item["name"])
                else:
                    # get write node:
                    write_node = item.get("other_params", dict()).get("node")
                    if not write_node:
                        errors.append("Could not find nuke node for item '%s'!" % item["name"])
                    else:
                        # do pre-publish:              
                        errors = self._nuke_pre_publish_write_node_render(write_node, write_node_app, progress_cb)
            
                
                #publishing files---
                # publish write-node rendered sequence                
                try:
                    (sg_publish, thumbnail_path) = self._publish_write_node_render(task, 
                                                                                   write_node, 
                                                                                   write_node_app, 
                                                                                   primary_publish_path, 
                                                                                   sg_task, 
                                                                                   comment, 
                                                                                   progress_cb)
                    
                    # keep track of our publish data so that we can pick it up later in review
                    render_publishes[ write_node.name() ] = (sg_publish, thumbnail_path)
                except Exception, e:
                    errors.append("Publish failed - %s" % e)
                
                #publishing to screening room---
                # Submit published sequence to Screening Room
                try:
                    
                    # If we have the tk-multi-reviewsubmission app we can create versions
                    review_submission_app = self.parent.engine.apps.get("tk-multi-reviewsubmission")

                    if not review_submission_app:
                        self.parent.log_warning("The Review Submission app can not be found. "
                                                "Shotgun Versions will not be automatically created.")
                    
                    else:
                        
                        # pick up sg data from the render dict we are maintianing
                        # note: we assume that the rendering tasks always happen
                        # before the review tasks inside the publish... 
                        (sg_publish, thumbnail_path) = render_publishes[ write_node.name() ]
                        
                        self._send_to_screening_room(
                            write_node,
                            write_node_app,
                            review_submission_app,
                            sg_publish,
                            sg_task,
                            comment,
                            thumbnail_path,
                            progress_cb
                        )

                except Exception, e:
                    errors.append("Submit to Screening Room failed - %s" % e)
            
            elif output_name == 'render_network':
                
                try:
                    self._network_render(item, output, work_template, primary_publish_path, 
                                         sg_task, comment, thumbnail_path, progress_cb)
                except Exception, e:
                    errors.append("Publish failed - %s" % e)
                   
            else:
                # this should never happen!
                errors.append("Don't know how to publish this item!")
                
            # if there is anything to report then add to result
            if len(errors) > 0:
                # add result:
                results.append({"task":task, "errors":errors})

            progress_cb(100)

        return results
    
    def _network_render(self, item, output, work_template, primary_publish_path, sg_task, comment, thumbnail_path, progress_cb):
        
        filePath=nuke.root()['name'].value() 
    
        name=os.path.basename(filePath)
        start=int(nuke.root()['first_frame'].value())
        end=int(nuke.root()['last_frame'].value())
        inputFilepath=filePath
        pluginArgs=['']
        submitArgs=['Comment=Shotgun Publish submit']
        shotgunContext=self.parent.context
        
        #getting fields for version
        shot_temp=self.parent.sgtk.templates["nuke_shot_work"]
        shotgunFields=shot_temp.get_fields(filePath)
        
        #getting output path
        area_temp=self.parent.sgtk.templates['nuke_shot_render_area']
        outputPath=area_temp.apply_fields(shotgunFields).replace('\\','/')
        
        #getting output fields
        render_temp=self.parent.sgtk.templates['nuke_shot_render_exr']
        outputFiles=render_temp.apply_fields(shotgunFields)
        outputFields=render_temp.get_fields(outputFiles)
        
        #replacing name with file name
        outputFields['name']='.'.join(filePath.split('/')[-1].split('.')[0:-2])
        
        #generate outputFiles
        shotgunFiles=render_temp.apply_fields(outputFields)
        
        #setting output
        publishFiles=[shotgunFiles]
          
        #clunky code to replace seq format with ?
        cmd=''
        maxCount=int(shotgunFiles.split('%')[-1].split('.')[0].replace('d',''))
        for count in xrange(0,maxCount):
            
            cmd+='?'
        
        path=shotgunFiles.split('%')[0][0:-1]
        ext=shotgunFiles.split('%')[-1].split('.')[-1]
        
        outputFile='.'.join([path,cmd,ext]).replace('\\','/')
        
        outputFiles=[outputFile]
        
        #getting login for user and replacing with user in shotgunContext
        shotgunUser=sgtk.util.get_current_user(self.parent.sgtk)
        
        #creating the folders for rendering
        for outputfile in outputFiles:
            
            dirpath=os.path.dirname(outputfile)
            
            if not os.path.exists(dirpath):
                os.makedirs(dirpath)
        
        #submit to deadline
        cdu.submit('nuke', name, start, end, inputFilepath, outputPath, outputFiles, pluginArgs, submitArgs,
                   shotgunContext=shotgunContext, shotgunFields=shotgunFields,shotgunUser=shotgunUser)
        
        # Finally, register this publish with Shotgun
        tank_type='Comp Render'
        name=item["name"]
        
        for outputfile in publishFiles:
            self._register_publish(outputfile,
                                   name,
                                   sg_task,
                                   shotgunFields['version'],
                                   tank_type,
                                   comment,
                                   thumbnail_path,
                                   [primary_publish_path])
    
    def _send_to_screening_room(self, write_node, write_node_app, review_submission_app, sg_publish, sg_task, comment, thumbnail_path, progress_cb):
        """
        Take a write node's published files and run them through the
        review_submission app to get a movie and Shotgun Version.
        """
        
        render_path = write_node_app.get_node_render_path(write_node)
        render_template = write_node_app.get_node_render_template(write_node)
        publish_template = write_node_app.get_node_publish_template(write_node)                        
        render_path_fields = render_template.get_fields(render_path)

        review_submission_app.render_and_submit(
            publish_template,
            render_path_fields,
            int(nuke.root()["first_frame"].value()),
            int(nuke.root()["last_frame"].value()),
            [sg_publish],
            sg_task,
            comment,
            thumbnail_path,
            progress_cb,
        )

    def _publish_write_node_render(self, task, write_node, write_node_app, published_script_path, sg_task, comment, progress_cb):
        """
        Publish render output for write node
        """
 
        if write_node_app.is_node_render_path_locked(write_node):
            # this is a fatal error as publishing would result in inconsistent paths for the rendered files!
            raise TankError("The render path is currently locked and does not match match the current Work Area.")
 
        progress_cb(10, "Finding renders")
 
        # get info we need in order to do the publish:
        render_path = write_node_app.get_node_render_path(write_node)
        render_files = write_node_app.get_node_render_files(write_node)
        render_template = write_node_app.get_node_render_template(write_node)
        publish_template = write_node_app.get_node_publish_template(write_node)                        
        tank_type = write_node_app.get_node_tank_type(write_node)
        
        # publish (copy files):
        
        progress_cb(25, "Copying files")
        
        for fi, rf in enumerate(render_files):
            
            progress_cb(25 + (50*(len(render_files)/(fi+1))))
            
            # construct the publish path:
            fields = render_template.get_fields(rf)
            fields["TankType"] = tank_type
            target_path = publish_template.apply_fields(fields)

            # copy the file
            try:
                target_folder = os.path.dirname(target_path)
                self.parent.ensure_folder_exists(target_folder)
                self.parent.copy_file(rf, target_path, task)
            except Exception, e:
                raise TankError("Failed to copy file from %s to %s - %s" % (rf, target_path, e))
            
        progress_cb(40, "Publishing to Shotgun")
            
        # use the render path to work out the publish 'file' and name:
        render_path_fields = render_template.get_fields(render_path)
        render_path_fields["TankType"] = tank_type
        publish_path = publish_template.apply_fields(render_path_fields)
            
        # construct publish name:
        publish_name = ""
        rp_name = render_path_fields.get("name")
        rp_channel = render_path_fields.get("channel")
        if rp_name is None and rp_channel is None:
            publish_name = "Publish"
        elif rp_name is None:
            publish_name = "Channel %s" % rp_channel
        elif rp_channel is None:
            publish_name = rp_name
        else:
            publish_name = "%s, Channel %s" % (rp_name, rp_channel)
        
        publish_version = render_path_fields["version"]
            
        # get/generate thumbnail:
        thumbnail_path = write_node_app.generate_node_thumbnail(write_node)
            
        # register the publish:
        sg_publish = self._register_publish(publish_path, 
                                            publish_name, 
                                            sg_task, 
                                            publish_version, 
                                            tank_type,
                                            comment,
                                            thumbnail_path, 
                                            [published_script_path])
        
        return sg_publish, thumbnail_path

    def _register_publish(self, path, name, sg_task, publish_version, tank_type, comment, thumbnail_path, dependency_paths):
        """
        Helper method to register publish using the 
        specified publish info.
        """
        # construct args:
        args = {
            "tk": self.parent.tank,
            "context": self.parent.context,
            "comment": comment,
            "path": path,
            "name": name,
            "version_number": publish_version,
            "thumbnail_path": thumbnail_path,
            "task": sg_task,
            "dependency_paths": dependency_paths,
            "published_file_type":tank_type,
        }
        
        # register publish;
        sg_data = tank.util.register_publish(**args)
        
        return sg_data
        
    def _nuke_pre_publish_write_node_render(self, write_node, write_node_app, progress_cb):
        """
        Pre-publish render output for write node
        """
        errors = []
        try:
            # check to see if the write node path is currently locked:
            if write_node_app.is_node_render_path_locked(write_node):
                # renders for the write node can't be published - trying to publish 
                # will result in an error in the publish hook!
                errors.append("The render path is currently locked and does not match match the current Work Area.")
            
            progress_cb(10.0, "Finding rendered files")
            
            # get list of render files:
            render_files = write_node_app.get_node_render_files(write_node)
            if len(render_files) == 0:
                is_valid = False
                errors.append("No render files exist to be published!")
            else:
                # ensure that published files don't already exist
        
                # need the render template, publish template and tank type which are all 
                # defined per node (profile) in the tk-nuke-writenode app
                render_template = write_node_app.get_node_render_template(write_node)
                publish_template = write_node_app.get_node_publish_template(write_node)                        
                tank_type = write_node_app.get_node_tank_type(write_node)
        
                progress_cb(25.0, "Checking for existing files")
                
                # check files:
                existing_files = []
                for fi, rf in enumerate(render_files):
                    
                    progress_cb(25 + (75*(len(render_files)/(fi+1))))
                    
                    # construct the publish path:
                    fields = render_template.get_fields(rf)
                    fields["TankType"] = tank_type
                    target_path = publish_template.apply_fields(fields)
                
                    if os.path.exists(target_path):
                        existing_files.append(target_path)
                        
                if existing_files:
                    # one or more published files already exist!
                    msg = "Published render file '%s'" % existing_files[0]
                    if len(existing_files) > 1:
                        msg += " (+%d others)" % (len(existing_files)-1)
                    msg += " already exists!"
                    errors.append(msg)
        except Exception, e:
            errors.append("Unhandled exception: %s" % e)

        return errors