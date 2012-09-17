from google.appengine.ext import db
import logging
from math import *

class Alert(Exception):
    pass

class Player(db.Model):
    network = db.StringProperty() # 'facebook','google+','twitter', etc
    userid = db.StringProperty() # network specific id - must be unique in the network
    nickname = db.StringProperty() # hnh specific name for user. defaults to either '<firstname> <lastname>' or '<username>'.
    @classmethod
    def get_or_create(cls,network,userid,nickname):
        key_name = '%s|%s' % (network,userid)
        return cls.get_or_insert(key_name,
                                  network=network,
                                  userid=userid,
                                  nickname=nickname
                                  )

class AttributeType(db.Model):
    ''' stores general information about each attribute a player can have
        use the 'create' method to add a new one
    '''
    name = db.StringProperty() # name of attribute: 'health', 'energy', etc
    description = db.StringProperty()
    min_value = db.FloatProperty(default=0.0)
    max_value = db.FloatProperty(default=100.0)
    default_value = db.FloatProperty(default=100.0) # the value that this attribute tends to
    color = db.StringProperty(default='#ddd') # html colour definition
    order = db.FloatProperty(default=10.0) # used to define the order of importance of attributes
    # expression: f(time_elapsed,initial_value,min_value,max_value,default_value) -> current_value
    change_formula = db.StringProperty()
    
    @staticmethod
    def linear(seconds_to_recovery):
        'max(0,min(100,initial_value+(time_elapsed*(max_value-min_value)/%s)))' % seconds_to_recovery

    # default change function recovers from 0 to max linearly in 1 hour
    DEFAULT_CHANGE_FUNCTION = linear(3600)
    
    @classmethod
    def create(klass,name,**kw):
        if not 'change_formula' not in kw:
            kw['change_formula'] = klass.DEFAULT_CHANGE_FUNCTION
        new_entity = klass(key_name=name,
                           name=name,
                           **kw)
        new_entity.put()
        return new_entity
    
class Attribute(db.Model):
    ''' latest snapshot of a particular attribute for a user
        parent: Player
        key: Player.key|AttributeType.name
    '''
    attribute_type = db.ReferenceProperty(AttributeType)
    name = db.StringProperty() # denormalised from AttributeType
    latest_value = db.FloatProperty()
    latest_date = db.DateTimeProperty(auto_now=True)
    @classmethod
    def get_or_prepare(klass,player,name,at=None):
        key_name = '%s|%s' % (player.key().name(),name)
        entity = klass.get_by_key_name(key_name,parent=player)
        if not entity:
            if not at:
                at = AttributeType.get_by_key_name(name)
            if not at:
                raise ValueError('attribute "%s" is not defined' % name)
            entity = klass(key_name=key_name,
                           parent=player,
                           attribute_type=at,
                           name=name,
                           latest_value=at.default_value)
        return entity
    @classmethod
    def get_or_create(klass,player,name):
        key_name = '%s|%s' % (player.key().name(),name)
        entity = klass.get_by_key_name(key_name,parent=player)
        if not entity:
            at = AttributeType.get_by_key_name(name)
            if not at:
                raise ValueError('attribute "%s" is not defined' % name)
            entity = klass.get_or_insert(key_name=key_name,
                                         parent=player,
                                         attribute_type=at,
                                         name=name,
                                         latest_value=at.default_value)
        return entity

''' 
# havent decided whether this should really be part of the datastore yet
# will implement these as code first

class ActionType(db.Model):
    name = db.StringProperty
    # has a collection property called 'effects'
    
class Effect(db.Model):
    # parent: ActionType
    attribute_type = db.ReferenceProperty(AttributeType)
    formula = db.StringProperty() # expression: f(scale) -> float effect on attribute
'''

''' default actions

    'action_name':  {
        'effects':  ([actor EFFECTs],[target EFFECTs]),
        'past_tense': 'text',
        }   

    EFFECT := (AttributeType,Lambda(scale))

'''
actions = {
    'heal': {
        'effects':      ([('energy',lambda s: -10.0*s)],[('health',lambda s: 5.0*s)]),
        'past_tense':   'healed',
        },
    'hurt': {
        'effects':      ([('energy',lambda s: -15.0*s)],[('health',lambda s: -10.0*s)]),
        'past_tense':   'hurt',
        },
    'revive': {
        'effects':      ([('energy',lambda s: -100.0)],[('health',lambda s: 25.0),('energy',lambda s: 25.0)],
        }
    }

from shardedcounter import get_count, increment

class Action(db.Model):
    ''' record the details of one person acting upon another
    '''
    actor = db.ReferenceProperty(Player,collection_name='actions')
    target = db.ReferenceProperty(Player,collection_name='incidents')
    date = db.DateTimeProperty()
    date_key = db.StringProperty()
    #action_type = db.ReferenceProperty(ActionType)
    action = db.StringProperty() # records which action was used
    narration = db.StringProperty() # user defined narration
    actor_effects = db.StringProperty() # summary of the effects
    target_effects = db.StringProperty() # summary of the effects

    def past_tense(self):
        ''' return the past tense of the action 
            should probably be stored with the action type
        '''
        try:
            return actions[self.action]['past_tense']
        except KeyError:
            return self.action

    def gen_age(self):
        ''' generate a nice text string to describe how long ago the action happened
            TODO: should really move this to the client side
        '''
        td = datetime.now() - self.date #relativedelta.relativedelta(now,self.date)
        if td.days >= 365 * 2:
            return 'more than %d years ago' % (td.days / 365)
        elif td.days >= 365:
            return 'more than a year ago'
        elif td.days >= 60:
            return 'more than %d months ago' % (td.days / 30)
        elif td.days >= 30:
            return 'more than a month ago'
        elif td.days >= 2:
            return '%d days ago' % td.days
        elif td.days >= 1:
            return 'one day ago'
        elif td.seconds >= 7200:
            return '%d hours ago' % (td.seconds / 3600)
        elif td.seconds >= 3600:
            return 'one hour ago'
        elif td.seconds >= 120:
            return '%d minutes ago' % (td.seconds / 60)
        elif td.seconds >= 60:
            return 'one minute ago'
        elif td.seconds >= 2:
            return '%d seconds ago' % td.seconds
        elif td.seconds >= 1:
            return 'one second ago'
        return 'just now'

    @classmethod
    def latest_action(cls,target):
        return cls.all().filter('target =',target).order('-date_key').get()

    @classmethod
    def recent_actions(cls,number=10):
        return cls.all().order('-date_key').fetch(number)

    @staticmethod
    def gen_date_key(date):
        ''' generates a key which can be used to sort entries in date order
            uses sharded counters to allow multiple actions in the same second
        
            be careful: the time format string below is designed to have 12 places to allow comparison of keys in order
            this will run out in the year 33679 - assuming the year 2038 problem is fixed :)
            to those that are maintaining the code in 33679CE: sorry! but i'm sure you'll be able to fix it and upgrade properly. 
            Say high to my descendants for me too!
        '''
        seconds = date.strftime('%012s')
        count = increment('action_%s'%seconds)
        return '%s|%s' % (seconds,count)

    @classmethod
    def create(cls,actor,target,date,action,narration,actor_effects,target_effects):
        ''' create a new action
        '''
        logging.warning('narration: %s' % narration)
        new_action = Action(actor=actor,
                       target=target,
                       date = date,
                       date_key=Action.gen_date_key(date),
                       action=action,
                       narration=narration,
                       actor_effects=actor_effects,
                       target_effects=target_effects)
        new_action.put()
        return new_action
