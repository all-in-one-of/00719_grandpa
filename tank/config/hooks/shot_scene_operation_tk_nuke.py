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
import nuke

import sgtk
import tank
from tank import Hook
from tank import TankError
from tank.platform.qt import QtGui

class SceneOperation(Hook):
    """
    Hook called to perform an operation with the 
    current scene
    """
    
    def execute(self, operation, file_path, context, parent_action, **kwargs):
        """
        Main hook entry point
        
        :operation:     String
                        Scene operation to perform
        
        :file_path:     String
                        File path to use if the operation
                        requires it (e.g. open)
                    
        :context:       Context
                        The context the file operation is being
                        performed in.
                    
        :parent_action: This is the action that this scene operation is
                        being executed for.  This can be one of: 
                        - open_file
                        - new_file
                        - save_file_as 
                        - version_up
                            
        :returns:       Depends on operation:
                        'current_path' - Return the current scene
                                         file path as a String
                        'reset'        - True if scene was reset to an empty 
                                         state, otherwise False
                        all others     - None
        """
        
        if file_path:
            file_path = file_path.replace("/", os.path.sep)
        
        if operation == "current_path":
            # return the current script path
            return nuke.root().name().replace("/", os.path.sep)
        
        elif operation == "prepare_new":
            
            #post setup---
            commands = sgtk.platform.current_engine().commands
            
            #setting frame range with sync app
            sync_cmd = commands["Sync Frame Range with Shotgun"]["callback"]
            
            sync_cmd()
            
            #prompting for an initial save as
            save_as_cmd = commands["Shotgun Save As..."]["callback"]
            
            save_as_cmd()
        
        elif operation == "open":
            # open the specified script
            nuke.scriptOpen(file_path)
            
            # reset any write node render paths:
            if self._reset_write_node_render_paths():
                # something changed so make sure to save the script again:
                nuke.scriptSave()
            
        elif operation == "save":
            # save the current script:
            nuke.scriptSave()
            
        elif operation == "save_as":
            old_path = nuke.root()["name"].value()
            try:
                # rename script:
                nuke.root()["name"].setValue(file_path)
                        
                # reset all write nodes:
                self._reset_write_node_render_paths()
                    
                # save script:
                nuke.scriptSaveAs(file_path, -1)    
            except Exception, e:
                # something went wrong so reset to old path:
                nuke.root()["name"].setValue(old_path)
                raise TankError("Failed to save scene %s", e)
            
            #updating shotgun status
            print 'updating shotgun status'
            
            taskId=context.task['id']
            sg=self.parent.shotgun
            
            data = {'sg_status_list':'ip' }
            
            sg.update("Task",taskId,data)
            
        elif operation == "reset":
            """
            Reset the scene to an empty state
            """
            while nuke.root().modified():
                # changes have been made to the scene
                res = QtGui.QMessageBox.question(None,
                                                 "Save your script?",
                                                 "Your script has unsaved changes. Save before proceeding?",
                                                 QtGui.QMessageBox.Yes|QtGui.QMessageBox.No|QtGui.QMessageBox.Cancel)
            
                if res == QtGui.QMessageBox.Cancel:
                    return False
                elif res == QtGui.QMessageBox.No:
                    break
                else:
                    nuke.scriptSave()

            # now clear the script:
            nuke.scriptClear()
            
            return True
        
        
    def _reset_write_node_render_paths(self):
        """
        Use the tk-nuke-writenode app interface to find and reset
        the render path of any Tank write nodes in the current script
        """
        write_node_app = self.parent.engine.apps.get("tk-nuke-writenode")
        if not write_node_app:
            return
        
        write_nodes = write_node_app.get_write_nodes()
        for write_node in write_nodes:
            write_node_app.reset_node_render_path(write_node)
            
        return len(write_nodes) > 0
        
        
