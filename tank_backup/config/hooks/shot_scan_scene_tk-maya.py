"""
Copyright (c) 2013 Shotgun Software, Inc
----------------------------------------------------

"""

import os
import maya.cmds as cmds
import pymel.core as pm

import tank
from tank import Hook
from tank import TankError

class ScanSceneHook(Hook):
    """
    Hook to scan scene for items to publish
    """
    
    def execute(self, **kwargs):
        """
        Main hook entry point
        :returns:       A list of any items that were found to be published.  
                        Each item in the list should be a dictionary containing 
                        the following keys:
                        {
                            type:   String
                                    This should match a scene_item_type defined in
                                    one of the outputs in the configuration and is 
                                    used to determine the outputs that should be 
                                    published for the item
                                    
                            name:   String
                                    Name to use for the item in the UI
                            
                            description:    String
                                            Description of the item to use in the UI
                                            
                            selected:       Bool
                                            Initial selected state of item in the UI.  
                                            Items are selected by default.
                                            
                            required:       Bool
                                            Required state of item in the UI.  If True then
                                            item will not be deselectable.  Items are not
                                            required by default.
                                            
                            other_params:   Dictionary
                                            Optional dictionary that will be passed to the
                                            pre-publish and publish hooks
                        }
        """   
        
        ctx=self.parent.context
          
        items = []
        
        # get the main scene:
        scene_name = cmds.file(query=True, sn=True)
        if not scene_name:
            raise TankError("Please Save your file before Publishing")
        
        scene_path = os.path.abspath(scene_name)
        name = os.path.basename(scene_path)

        # create the primary item - this will match the primary output 'scene_item_type':            
        items.append({"type": "work_file", "name": name})
        
        #create alembic items
        assets={}
        nodes=[]
        
        if ctx.step['name']!='Light':
            for node in pm.ls(type='transform'):        
                if pm.PyNode(node).hasAttr('asset'):            
                    assetName=cmds.getAttr(node+'.asset')
                    assets[assetName]=[]            
                    nodes.append(node)
                if pm.PyNode(node).hasAttr('abcStep'):            
                    assetName='extras'
                    assets[assetName]=[]            
                    nodes.append(node)
            
            if len(nodes)>0:
                for node in nodes:  
                    assetName=cmds.getAttr(node+'.asset')
                    assets[assetName].append(node)  
                    if pm.PyNode(node).hasAttr('abcStep'):  
                        assetName='extras'
                        assets[assetName].append(node)        
                                 
            for asset in assets:
                items.append({"type":"asset", "name":asset, "other_params": assets[asset] })
        
        #create Preview items
        cameras=pm.ls(type='camera')
        for node in cameras:  
            if node != 'frontShape' and node != 'sideShape' and node != 'topShape' and node != 'perspShape':
                items.append({"type": "shotcam", "name": node.getParent().name().split(':')[-1], "other_params": [node.getParent()]})
        
        #adding Render item
        if ctx.step['name']=='Light':
            items.append({"type": "render", "name": 'render'})
        
        return items
