#!/usr/bin/env python

# google app engine imports
import webapp2
from google.appengine.ext.webapp import template
from google.appengine.ext import db  

# standard python imports
from datetime import datetime
import logging
import random

# hurt'n'heal specific imports
import hnh
from facebook import *

class MainHandler(webapp2.RequestHandler):
    def get(self):
        self.response.out.write(template.render('index.html',{}))

    def post(self):
        sig, payload = self.request.get('signed_request').split('.',1)
        sr = decode_signed_req(payload)
        
        if 'oauth_token' not in sr:
            self.response.out.write(template.render('index.html',{
                'signed_request': self.request.get('signed_request'),
                'not_authorised': True,
                }))
            return
        
        logging.warning('oauth_token provided')
        
        graph = get_facebook_data('graph',sr['oauth_token'])
        friends = get_facebook_data('friends',sr['oauth_token'])
        friends_to_display = random.sample(get_facebook_friends(sr['oauth_token']),10)
        friend_players = [hnh.Player.get_or_create('facebook',f['id'],f['name']) for f in friends_to_display]
        
        player = hnh.Player.get_or_create('facebook',graph['id'],graph['name'])
        
        action = self.request.get('action')
        
        if action:
            try:
                target = hnh.Player.get_or_create(self.request.get('target_network'),
                                                  self.request.get('target_id'),
                                                  self.request.get('target_username'))
                hnh.perform_action(player,target,action,1.0,self.request.get('narration'))
                player = hnh.Player.get_by_key_name('facebook|%s' % graph['id'])
            except hnh.Alert, a:
                logging.warning(a)           
                
        reftime = datetime.now()
        #friend_snapshots = [hnh.get_current_info(p,reftime) for p in friend_players]
        recent_actions = hnh.Action.recent_actions()
        
        # player centric view
        player_info = {}
        for action in recent_actions:
            target_key = action.target.key().name()
            if target_key not in player_info and target_key != player.key().name():
                player_info[target_key] = {
                    'action': action, 
                    'status': hnh.get_current_info(action.target,reftime),
                    'person': action.target,
                    'test': 'acted',
                    }
            else: # skip players we've already seen                
                pass
        left_over = 10 - len(player_info)
        random.shuffle(friend_players)
        for p in friend_players:
            if p.key().name() in player_info:
                continue
            player_info[p.key().name()] = {
                'action': None,
                'status': hnh.get_current_info(p,reftime),
                'person': p,
                'test': 'random',
                }
        
        # action centric view
        '''
        snapshots = {}
        for action in recent_actions:
            key_name = action.target.key().name()
            if key_name not in snapshots:
                snapshots[key_name] = hnh.get_current_info(action.target,reftime)
            action.target_snapshot = snapshots[key_name]
        '''
            
        status = hnh.get_current_info(player,reftime)
        self.response.out.write(template.render('index.html',{
            'signed_request': self.request.get('signed_request'),
            'user'          : graph,
            'player'        : player,
            'status'        : status,
            #'friends'       : friend_snapshots,
            'action'        : status.last_action,
            'recent'        : recent_actions,
            'interesting'   : player_info,
            }))


class InitHandler(webapp2.RequestHandler):
    ''' use this once to install the attribute types
    '''
    def get(self):
        hnh.AttributeType.create('health',
                                 change_formula=hnh.AttributeType.linear(3600),
                                 color='#beb',
                                 order=0.0,
                                 description='the state of your health. 0 means death!')
        hnh.AttributeType.create('energy',
                                 change_formula=hnh.AttributeType.linear(1800),
                                 color='#bbe',
                                 order=1.0,
                                 description='most actions require energy to perform')

#from sessions import get_current_session

app = webapp2.WSGIApplication([('/', MainHandler),
                               ('/init', InitHandler)
                               ],debug=True)
