# google app engine imports
import webapp2
from google.appengine.ext.webapp import template
from google.appengine.ext import db  

# standard python imports
from datetime import datetime
import logging
import random

# hurt'n'heal specific imports
from models import Player, Action, AttributeType
from hnh import act, Alert, get_current_info

from facebook import *


class MainHandler(webapp2.RequestHandler):
    def get(self):
        return self.post()

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
        
        player = Player.get_or_create('facebook',graph['id'],graph['name'])
        
        action = self.request.get('action')
        
        if action:
            try:
                target = Player.get_or_create(self.request.get('target_network'),
                                              self.request.get('target_id'),
                                              self.request.get('target_username'))
                act(player,target,action,self.request.get('narration'))
                player = Player.get_by_key_name('facebook|%s' % graph['id']) # TODO: figure out why I have this step and comment on it
            except Alert, a:
                logging.warning(a)           
                
        reftime = datetime.now()
        recent_actions = Action.recent_actions()
        
        player_info = []
        included_players = set()
        for action in recent_actions:
            target_key = action.target.key().name()
            if target_key not in included_players and target_key != player.key().name():
                included_players.add(target_key)
                player_info.append({
                    'action': action, 
                    'status': get_current_info(action.target,reftime),
                    'person': action.target,})
        left_over = 10 - len(player_info)
        friends_to_display = random.sample(get_facebook_friends(sr['oauth_token']),left_over)
        friend_players = [Player.get_or_create('facebook',f['id'],f['name']) for f in friends_to_display]        
        random.shuffle(friend_players)
        for p in friend_players:
            if p.key().name() in included_players:
                continue
            included_players.add(p.key().name())
            player_info.append({
                'action': None,
                'status': get_current_info(p,reftime),
                'person': p,
                })
            
        status = get_current_info(player,reftime)
        self.response.out.write(template.render('index.html',{
            'signed_request': self.request.get('signed_request'),
            'user'          : graph,
            'player'        : player,
            'status'        : status,
            'action'        : status['last_action'],
            'recent'        : recent_actions,
            'interesting'   : [{'person':player,'action':status['last_action'],'status':status}]+player_info,
            }))


class CurrentStatusHandler(webapp2.RequestHandler):
    def get(self):
        return post(self)
       
    def get(self,network,id):
       
        target = Player.get_by_key_name(Player.make_key(network,id))
        refdate = self.request.get('refdate',None)
        self.response.out.write(template.render('status.html',{
            'status' : get_current_info(target,refdate),
            'person' : target,
            'action' : None,        
            }))

class UpdateHandler(webapp2.RequestHandler):
    """ utility handler to do updates required by schema changes
    """
    def get(self):
        ats = AttributeType.all().fetch(1000)
        for at in ats:
            at.recovery="1.0"
            at.decay="2.0"
            at.put()

class InitHandler(webapp2.RequestHandler):
    """ use this once to install the attribute types
    """
    def get(self):
        AttributeType.create('health',
                             color='#beb',
                             order=0.0,
                             recovery="0.1",
                             decay="1.0",
                             description='the state of your health. 0 means death!')
        AttributeType.create('energy',
                             color='#bbe',
                             order=1.0,
                             recovery="0.5",
                             decay="1.0",
                             description='most actions require energy to perform')

app = webapp2.WSGIApplication([('/', MainHandler),
                               ('/init', InitHandler),
                               ('/update', UpdateHandler),
                               ('/api/status/(.*)/(.*)', CurrentStatusHandler),
                               ],debug=True)
