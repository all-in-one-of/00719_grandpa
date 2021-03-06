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
import uuid
import tempfile

import tank
from tank import Hook
from tank import TankError

class PrimaryPublishHook(Hook):
    """
    Single hook that implements publish of the primary task
    """    
    def execute(self, task, work_template, comment, thumbnail_path, sg_task, progress_cb, **kwargs):
        """
        Main hook entry point
        :task:          Primary task to be published.  This is a
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
                        
        :progress_cb:   Function
                        A progress callback to log progress during pre-publish.  Call:
                        
                            progress_cb(percentage, msg)
                             
                        to report progress to the UI
        
        :returns:       Path String
                        Hook should return the path of the primary publish so that it
                        can be passed as a dependency to all secondary publishes
        
                        Hook should raise a TankError if publish of the 
                        primary task fails
        """
        # get the engine name from the parent object (app/engine/etc.)
        engine_name = self.parent.engine.name
        
        # depending on engine:
        if engine_name == "tk-maya":
            return self._do_maya_publish(task, work_template, comment, thumbnail_path, sg_task, progress_cb)
        elif engine_name == "tk-nuke":
            return self._do_nuke_publish(task, work_template, comment, thumbnail_path, sg_task, progress_cb)
        elif engine_name == "tk-3dsmax":
            return self._do_3dsmax_publish(task, work_template, comment, thumbnail_path, sg_task, progress_cb)
        elif engine_name == "tk-hiero":
            return self._do_hiero_publish(task, work_template, comment, thumbnail_path, sg_task, progress_cb)
        elif engine_name == "tk-houdini":
            return self._do_houdini_publish(task, work_template, comment, thumbnail_path, sg_task, progress_cb)
        elif engine_name == "tk-softimage":
            return self._do_softimage_publish(task, work_template, comment, thumbnail_path, sg_task, progress_cb)
        elif engine_name == "tk-photoshop":
            return self._do_photoshop_publish(task, work_template, comment, thumbnail_path, sg_task, progress_cb)
        else:
            raise TankError("Unable to perform publish for unhandled engine %s" % engine_name)
        
    def _do_maya_publish(self, task, work_template, comment, thumbnail_path, sg_task, progress_cb):
        """
        Publish the main Maya scene
        """
        import maya.cmds as cmds
        
        progress_cb(0.0, "Finding scene dependencies", task)
        dependencies = self._maya_find_additional_scene_dependencies()
        
        # get scene path
        scene_path = os.path.abspath(cmds.file(query=True, sn=True))
        
        if not work_template.validate(scene_path):
            raise TankError("File '%s' is not a valid work path, unable to publish!" % scene_path)
        
        # use templates to convert to publish path:
        output = task["output"]
        fields = work_template.get_fields(scene_path)
        fields["TankType"] = output["tank_type"]
        publish_template = output["publish_template"]
        publish_path = publish_template.apply_fields(fields)
        
        sg_step = fields["Step"]
                
        #Get correct Tank Type from the context
        if sg_step == 'Model':
            output["tank_type"] = 'Maya Model'
        elif sg_step == 'Lookdev' and fields['filetag']=='shaded':
            output["tank_type"] = 'Maya Shaded Model'
        elif sg_step == 'Lookdev' and fields['filetag']=='light':
            output["tank_type"] = 'Maya Lighting'
        elif sg_step == 'Rig' and fields['filetag']=='skin':
            output["tank_type"] = 'Maya Deformation' 
        elif sg_step == 'Rig' and fields['filetag']=='rig':
            output["tank_type"] = 'Maya Rig' 
        
        if os.path.exists(publish_path):
            raise TankError("The published file named '%s' already exists!" % publish_path)
        
        # save the scene:
        progress_cb(10.0, "Saving the scene")
        self.parent.log_debug("Saving the scene...")
        cmds.file(save=True, force=True)
        
        # copy the file:
        progress_cb(50.0, "Copying the file")
        try:
            publish_folder = os.path.dirname(publish_path)
            self.parent.ensure_folder_exists(publish_folder)
            self.parent.log_debug("Copying %s --> %s..." % (scene_path, publish_path))
            self.parent.copy_file(scene_path, publish_path, task)
        except Exception, e:
            raise TankError("Failed to copy file from %s to %s - %s" % (scene_path, publish_path, e))

        # work out publish name:
        publish_name = self._get_publish_name(publish_path, publish_template, fields)

        # finally, register the publish:
        progress_cb(75.0, "Registering the publish")
        self._register_publish(publish_path, 
                               publish_name, 
                               sg_task, 
                               fields["version"], 
                               output["tank_type"],
                               comment,
                               thumbnail_path, 
                               dependencies
                               )
        
        progress_cb(100)
        
        return publish_path
        
    def _maya_find_additional_scene_dependencies(self):
        """
        Find additional dependencies from the scene
        """
        import maya.cmds as cmds

        # default implementation looks for references and 
        # textures (file nodes) and returns any paths that
        # match a template defined in the configuration
        ref_paths = set()
        
        # first let's look at maya references     
        ref_nodes = cmds.ls(references=True)
        for ref_node in ref_nodes:
            # get the path:
            ref_path = cmds.referenceQuery(ref_node, filename=True)
            # make it platform dependent
            # (maya uses C:/style/paths)
            ref_path = ref_path.replace("/", os.path.sep)
            if ref_path:
                ref_paths.add(ref_path)
            
        # now look at file texture nodes    
        for file_node in cmds.ls(l=True, type="file"):
            # ensure this is actually part of this scene and not referenced
            if cmds.referenceQuery(file_node, isNodeReferenced=True):
                # this is embedded in another reference, so don't include it in the
                # breakdown
                continue

            # get path and make it platform dependent
            # (maya uses C:/style/paths)
            texture_path = cmds.getAttr("%s.fileTextureName" % file_node).replace("/", os.path.sep)
            if texture_path:
                ref_paths.add(texture_path)
            
        # now, for each reference found, build a list of the ones
        # that resolve against a template:
        dependency_paths = []
        for ref_path in ref_paths:
            # see if there is a template that is valid for this path:
            for template in self.parent.tank.templates.values():
                if template.validate(ref_path):
                    dependency_paths.append(ref_path)
                    break

        return dependency_paths
    
        
    def _do_3dsmax_publish(self, task, work_template, comment, thumbnail_path, sg_task, progress_cb):
        """
        Publish the main 3ds Max scene
        """
        from Py3dsMax import mxs
        
        progress_cb(0.0, "Finding scene dependencies", task)
        dependencies = self._3dsmax_find_additional_scene_dependencies()
        
        # get scene path
        scene_path = os.path.abspath(os.path.join(mxs.maxFilePath, mxs.maxFileName))
        
        if not work_template.validate(scene_path):
            raise TankError("File '%s' is not a valid work path, unable to publish!" % scene_path)
        
        # use templates to convert to publish path:
        output = task["output"]
        fields = work_template.get_fields(scene_path)
        fields["TankType"] = output["tank_type"]
        publish_template = output["publish_template"]
        publish_path = publish_template.apply_fields(fields)
        
        if os.path.exists(publish_path):
            raise TankError("The published file named '%s' already exists!" % publish_path)
        
        # save the scene:
        progress_cb(10.0, "Saving the scene")
        self.parent.log_debug("Saving the scene...")
        mxs.saveMaxFile(scene_path)
        
        # copy the file:
        progress_cb(50.0, "Copying the file")
        try:
            publish_folder = os.path.dirname(publish_path)
            self.parent.ensure_folder_exists(publish_folder)
            self.parent.log_debug("Copying %s --> %s..." % (scene_path, publish_path))
            self.parent.copy_file(scene_path, publish_path, task)
        except Exception, e:
            raise TankError("Failed to copy file from %s to %s - %s" % (scene_path, publish_path, e))

        # work out publish name:
        publish_name = self._get_publish_name(publish_path, publish_template, fields)

        # finally, register the publish:
        progress_cb(75.0, "Registering the publish")
        self._register_publish(publish_path, 
                               publish_name, 
                               sg_task, 
                               fields["version"], 
                               output["tank_type"],
                               comment,
                               thumbnail_path, 
                               dependencies)
        
        progress_cb(100)
        
        return publish_path

    def _3dsmax_find_additional_scene_dependencies(self):
        """
        Find additional dependencies from the scene
        """
        # default implementation does nothing!
        return []


    def _do_hiero_publish(self, task, work_template, comment, thumbnail_path, sg_task, progress_cb):
        """
        Publish the currently selected hiero project.
        """
        import hiero.core
        
        # first find which the current project is. Hiero is a multi project 
        # environment so we can ask the engine which project was clicked in order
        # to launch this publish.
        
        selection = self.parent.engine.get_menu_selection()
        
        # these values should in theory already be validated, but just in case...
        if len(selection) != 1:
            raise TankError("Please select a single Project!")
        if not isinstance(selection[0] , hiero.core.Bin):
            raise TankError("Please select a Hiero Project!")
        project = selection[0].project()
        if project is None:
            # apparently bins can be without projects (child bins I think)
            raise TankError("Please select a Hiero Project!")
        
        progress_cb(0.0, "Finding scene dependencies", task)
        dependencies = self._hiero_find_additional_scene_dependencies()
        
        # get scene path
        scene_path = os.path.abspath(project.path().replace("/", os.path.sep))

        if not work_template.validate(scene_path):
            raise TankError("File '%s' is not a valid work path, unable to publish!" % scene_path)

        # use templates to convert to publish path:
        output = task["output"]
        fields = work_template.get_fields(scene_path)
        fields["TankType"] = output["tank_type"]
        publish_template = output["publish_template"]
        publish_path = publish_template.apply_fields(fields)

        if os.path.exists(publish_path):
            raise TankError("The published file named '%s' already exists!" % publish_path)

        # save the scene:
        progress_cb(10.0, "Saving the scene")
        self.parent.log_debug("Saving the scene...")
        project.save()

        # copy the file:
        progress_cb(50.0, "Copying the file")
        try:
            publish_folder = os.path.dirname(publish_path)
            self.parent.ensure_folder_exists(publish_folder)
            self.parent.log_debug("Copying %s --> %s..." % (scene_path, publish_path))
            self.parent.copy_file(scene_path, publish_path, task)
        except Exception, e:
            raise TankError("Failed to copy file from %s to %s - %s" % (scene_path, publish_path, e))

        # work out publish name:
        publish_name = self._get_publish_name(publish_path, publish_template, fields)

        # finally, register the publish:
        progress_cb(75.0, "Registering the publish")
        self._register_publish(publish_path,
                               publish_name,
                               sg_task,
                               fields["version"],
                               output["tank_type"],
                               comment,
                               thumbnail_path,
                               dependencies)

        progress_cb(100)

        return publish_path

        

    def _hiero_find_additional_scene_dependencies(self):
        """
        Find additional dependencies from the scene
        """
        # default implementation does nothing!
        return []


        
    def _do_nuke_publish(self, task, work_template, comment, thumbnail_path, sg_task, progress_cb):
        """
        Publish the main Nuke script
        """
        import nuke
        
        progress_cb(0.0, "Finding dependencies", task)
        dependencies = self._nuke_find_script_dependencies()
        
        # get scene path
        script_path = nuke.root().name().replace("/", os.path.sep)
        if script_path == "Root":
            script_path = ""
        script_path = os.path.abspath(script_path)
        
        if not work_template.validate(script_path):
            raise TankError("File '%s' is not a valid work path, unable to publish!" % script_path)
        
        # use templates to convert to publish path:
        output = task["output"]
        fields = work_template.get_fields(script_path)
        fields["TankType"] = output["tank_type"]
        publish_template = output["publish_template"]
        publish_path = publish_template.apply_fields(fields)
        
        if os.path.exists(publish_path):
            raise TankError("The published file named '%s' already exists!" % publish_path)
        
        # save the scene:
        progress_cb(25.0, "Saving the script")
        self.parent.log_debug("Saving the Script...")
        nuke.scriptSave()
        
        # copy the file:
        progress_cb(50.0, "Copying the file")
        try:
            publish_folder = os.path.dirname(publish_path)
            self.parent.ensure_folder_exists(publish_folder)
            self.parent.log_debug("Copying %s --> %s..." % (script_path, publish_path))
            self.parent.copy_file(script_path, publish_path, task)
        except Exception, e:
            raise TankError("Failed to copy file from %s to %s - %s" % (script_path, publish_path, e))

        # work out name for publish:
        publish_name = self._get_publish_name(publish_path, publish_template, fields)

        # finally, register the publish:
        progress_cb(75.0, "Registering the publish")
        self._register_publish(publish_path, 
                               publish_name, 
                               sg_task, 
                               fields["version"], 
                               output["tank_type"],
                               comment,
                               thumbnail_path, 
                               dependencies)
        
        progress_cb(100)
        
        return publish_path
        
    def _nuke_find_script_dependencies(self):
        """
        Find all dependencies for the current nuke script
        """
        import nuke
        
        # figure out all the inputs to the scene and pass them as dependency candidates
        dependency_paths = []
        for read_node in nuke.allNodes("Read"):
            # make sure we normalize file paths
            file_name = read_node.knob("file").evaluate().replace('/', os.path.sep)
            # validate against all our templates
            for template in self.parent.tank.templates.values():
                if template.validate(file_name):
                    fields = template.get_fields(file_name)
                    # translate into a form that represents the general
                    # tank write node path.
                    fields["SEQ"] = "FORMAT: %d"
                    fields["eye"] = "%V"
                    dependency_paths.append(template.apply_fields(fields))
                    break

        return dependency_paths

    def _do_houdini_publish(self, task, work_template, comment, thumbnail_path, sg_task, progress_cb):
        """
        Publish the main Houdini scene
        """
        import hou

        progress_cb(0.0, "Finding scene dependencies", task)
        dependencies = self._houdini_find_additional_scene_dependencies()

        # get scene path
        scene_path = os.path.abspath(hou.hipFile.name())

        if not work_template.validate(scene_path):
            raise TankError("File '%s' is not a valid work path, unable to publish!" % scene_path)

        # use templates to convert to publish path:
        output = task["output"]
        fields = work_template.get_fields(scene_path)
        fields["TankType"] = output["tank_type"]
        publish_template = output["publish_template"]
        publish_path = publish_template.apply_fields(fields)

        if os.path.exists(publish_path):
            raise TankError("The published file named '%s' already exists!" % publish_path)

        # save the scene:
        progress_cb(10.0, "Saving the scene")
        self.parent.log_debug("Saving the scene...")
        hou.hipFile.save()

        # copy the file:
        progress_cb(50.0, "Copying the file")
        try:
            publish_folder = os.path.dirname(publish_path)
            self.parent.ensure_folder_exists(publish_folder)
            self.parent.log_debug("Copying %s --> %s..." % (scene_path, publish_path))
            self.parent.copy_file(scene_path, publish_path, task)
        except Exception, e:
            raise TankError("Failed to copy file from %s to %s - %s" % (scene_path, publish_path, e))

        # work out publish name:
        publish_name = self._get_publish_name(publish_path, publish_template, fields)

        # finally, register the publish:
        progress_cb(75.0, "Registering the publish")
        self._register_publish(publish_path,
                               publish_name,
                               sg_task,
                               fields["version"],
                               output["tank_type"],
                               comment,
                               thumbnail_path,
                               dependencies)

        progress_cb(100)

        return publish_path

    def _houdini_find_additional_scene_dependencies(self):
        """
        Find additional dependencies from the scene
        """
        # initial implementation does nothing!
        return []

    def _do_softimage_publish(self, task, work_template, comment, thumbnail_path, sg_task, progress_cb):
        """
        Publish the main Softimage scene
        """
        import win32com
        from win32com.client import Dispatch, constants
        from pywintypes import com_error
        Application = Dispatch("XSI.Application").Application

        progress_cb(0.0, "Finding scene dependencies", task)
        dependencies = self._softimage_find_additional_scene_dependencies()

        # get scene path
        scene_path = os.path.abspath(Application.ActiveProject.ActiveScene.filename.value)

        if not work_template.validate(scene_path):
            raise TankError("File '%s' is not a valid work path, unable to publish!" % scene_path)

        # use templates to convert to publish path:
        output = task["output"]
        fields = work_template.get_fields(scene_path)
        fields["TankType"] = output["tank_type"]
        publish_template = output["publish_template"]
        publish_path = publish_template.apply_fields(fields)

        if os.path.exists(publish_path):
            raise TankError("The published file named '%s' already exists!" % publish_path)

        # save the scene:
        progress_cb(10.0, "Saving the scene")
        self.parent.log_debug("Saving the scene...")
        Application.SaveScene()

        # copy the file:
        progress_cb(50.0, "Copying the file")
        try:
            publish_folder = os.path.dirname(publish_path)
            self.parent.ensure_folder_exists(publish_folder)
            self.parent.log_debug("Copying %s --> %s..." % (scene_path, publish_path))
            self.parent.copy_file(scene_path, publish_path, task)
        except Exception, e:
            raise TankError("Failed to copy file from %s to %s - %s" % (scene_path, publish_path, e))

        # work out publish name:
        publish_name = self._get_publish_name(publish_path, publish_template, fields)

        # finally, register the publish:
        progress_cb(75.0, "Registering the publish")
        self._register_publish(publish_path,
                               publish_name,
                               sg_task,
                               fields["version"],
                               output["tank_type"],
                               comment,
                               thumbnail_path,
                               dependencies)

        progress_cb(100)

        return publish_path

    def _softimage_find_additional_scene_dependencies(self):
        """
        Find additional dependencies from the scene
        """
        # initial implementation does nothing!
        return []

    def _do_photoshop_publish(self, task, work_template, comment, thumbnail_path, sg_task, progress_cb):
        """
        Publish the main Photoshop scene
        """
        import photoshop
                
        doc = photoshop.app.activeDocument
        if doc is None:
            raise TankError("There is no currently active document!")
                
        # get scene path
        scene_path = doc.fullName.nativePath
        
        if not work_template.validate(scene_path):
            raise TankError("File '%s' is not a valid work path, unable to publish!" % scene_path)
        
        # use templates to convert to publish path:
        output = task["output"]
        fields = work_template.get_fields(scene_path)
        fields["TankType"] = output["tank_type"]
        publish_template = output["publish_template"]
        publish_path = publish_template.apply_fields(fields)
        
        if os.path.exists(publish_path):
            raise TankError("The published file named '%s' already exists!" % publish_path)
        
        # save the scene:
        progress_cb(0.0, "Saving the scene")
        self.parent.log_debug("Saving the scene...")
        doc.save()
        
        # copy the file:
        progress_cb(25.0, "Copying the file")
        try:
            publish_folder = os.path.dirname(publish_path)
            self.parent.ensure_folder_exists(publish_folder)
            self.parent.log_debug("Copying %s --> %s..." % (scene_path, publish_path))
            self.parent.copy_file(scene_path, publish_path, task)
        except Exception, e:
            raise TankError("Failed to copy file from %s to %s - %s" % (scene_path, publish_path, e))

        # work out publish name:
        publish_name = self._get_publish_name(publish_path, publish_template, fields)

        # finally, register the publish:
        progress_cb(50.0, "Registering the publish")
        tank_publish = self._register_publish(publish_path, 
                                              publish_name, 
                                              sg_task, 
                                              fields["version"], 
                                              output["tank_type"],
                                              comment,
                                              thumbnail_path, 
                                              dependency_paths=[])
        
        #################################################################################
        # create a version!
        
        jpg_pub_path = os.path.join(tempfile.gettempdir(), "%s_sgtk.jpg" % uuid.uuid4().hex)
        
        thumbnail_file = photoshop.RemoteObject('flash.filesystem::File', jpg_pub_path)
        jpeg_options = photoshop.RemoteObject('com.adobe.photoshop::JPEGSaveOptions')
        # save as a copy
        photoshop.app.activeDocument.saveAs(thumbnail_file, jpeg_options, True)        
        
        # then register version
        progress_cb(60.0, "Creating Version...")
        ctx = self.parent.context
        data = {
            "user": ctx.user,
            "description": comment,
            "sg_first_frame": 1,
            "frame_count": 1,
            "frame_range": "1-1",
            "sg_last_frame": 1,
            "entity": ctx.entity,
            "sg_path_to_frames": publish_path,
            "project": ctx.project,
            "sg_task": sg_task,
            "code": tank_publish["code"],
            "created_by": ctx.user,
        }
        
        if tank.util.get_published_file_entity_type(self.parent.tank) == "PublishedFile":
            data["published_files"] = [tank_publish]
        else:# == "TankPublishedFile"
            data["tank_published_file"] = tank_publish
        
        version = self.parent.shotgun.create("Version", data)
        
        # upload jpeg
        progress_cb(70.0, "Uploading to Shotgun...")
        self.parent.shotgun.upload("Version", version['id'], jpg_pub_path, "sg_uploaded_movie" )
        
        try:
            os.remove(jpg_pub_path)
        except:
            pass
        
        progress_cb(100)
        
        return publish_path
    
    def _get_publish_name(self, path, template, fields=None):
        """
        Return the 'name' to be used for the file - if possible
        this will return a 'versionless' name
        """
        # first, extract the fields from the path using the template:
        fields = fields.copy() if fields else template.get_fields(path)
        if "name" in fields and fields["name"]:
            # well, that was easy!
            name = fields["name"]
        else:
            # find out if version is used in the file name:
            template_name, _ = os.path.splitext(os.path.basename(template.definition))
            version_in_name = "{version}" in template_name
        
            # extract the file name from the path:
            name, _ = os.path.splitext(os.path.basename(path))
            delims_str = "_-. "
            if version_in_name:
                # looks like version is part of the file name so we        
                # need to isolate it so that we can remove it safely.  
                # First, find a dummy version whose string representation
                # doesn't exist in the name string
                version_key = template.keys["version"]
                dummy_version = 9876
                while True:
                    test_str = version_key.str_from_value(dummy_version)
                    if test_str not in name:
                        break
                    dummy_version += 1
                
                # now use this dummy version and rebuild the path
                fields["version"] = dummy_version
                path = template.apply_fields(fields)
                name, _ = os.path.splitext(os.path.basename(path))
                
                # we can now locate the version in the name and remove it
                dummy_version_str = version_key.str_from_value(dummy_version)
                
                v_pos = name.find(dummy_version_str)
                # remove any preceeding 'v'
                pre_v_str = name[:v_pos].rstrip("v")
                post_v_str = name[v_pos + len(dummy_version_str):]
                
                if (pre_v_str and post_v_str 
                    and pre_v_str[-1] in delims_str 
                    and post_v_str[0] in delims_str):
                    # only want one delimiter - strip the second one:
                    post_v_str = post_v_str.lstrip(delims_str)

                versionless_name = pre_v_str + post_v_str
                versionless_name = versionless_name.strip(delims_str)
                
                if versionless_name:
                    # great - lets use this!
                    name = versionless_name
                else: 
                    # likely that version is only thing in the name so 
                    # instead, replace the dummy version with #'s:
                    zero_version_str = version_key.str_from_value(0)        
                    new_version_str = "#" * len(zero_version_str)
                    name = name.replace(dummy_version_str, new_version_str)
        
        return name     
     

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
            "published_file_type":tank_type
        }
        
        self.parent.log_debug("Register publish in shotgun: %s" % str(args))
        
        # register publish;
        sg_data = tank.util.register_publish(**args)
        
        return sg_data
