from google.appengine.ext import db
import logging

from datetime import datetime
from caching import instance_cache


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
    """ stores general information about each attribute a player can have
        use the 'create' method to add a new one
    """
    name = db.StringProperty() # name of attribute: 'health', 'energy', etc
    description = db.StringProperty()
    min_value = db.FloatProperty(default=0.0)
    max_value = db.FloatProperty(default=100.0)
    default_value = db.FloatProperty(default=100.0) # the value that this attribute tends to
    color = db.StringProperty(default='#ddd') # html colour definition
    order = db.FloatProperty(default=10.0) # used to define the order of importance of attributes
    
    # string contains formula that returns the recovery/decay rate per second
    # f(Thespian) -> float
    recovery = db.StringProperty(default="1.0")
    decay = db.StringProperty(default="1.0")
    
    @classmethod
    def create(klass,name,**kw):
        new_entity = klass(key_name=name,
                           name=name,
                           **kw)
        new_entity.put()
        return new_entity


    
class Attribute(db.Model):
    """ latest snapshot of a particular attribute for a user
        parent: Player
        key: Player.key|AttributeType.name
    """
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


# create a safe context for eval and exec statements
safe_functs = ['math','acos', 'asin', 'atan', 'atan2', 'ceil', 
               'cos', 'cosh', 'degrees', 'e', 'exp', 'fabs', 
               'floor', 'fmod', 'frexp', 'hypot', 'ldexp', 'log', 
               'log10', 'modf', 'pi', 'pow', 'radians', 'sin', 
               'sinh', 'sqrt', 'tan', 'tanh']
base_ctx = dict([(k,locals().get(k,None)) for k in safe_functs])
base_ctx['abs'] = abs
base_ctx['min'] = min
base_ctx['max'] = max

class ActionType(object):
    def __init__(self,present_tense,past_tense,script):
        self.present_tense = present_tense
        self.past_tense = past_tense
        self.compiled_script = compile(script,'<string>','exec')
    def run_script(self,actor,target):
        ''' script(Thespian,Thespian) -> None
            outputs are all via side-effects of Thespian.add_effect()
        '''
        cache_key = 'AttributeType.all()'
        all_attr_types = instance_cache.get(cache_key)
        if not all_attr_types:
            all_attr_types = AttributeType.all().fetch(100)
            instance_cache.set(cache_key,all_attr_types)
        global_ctx = {'__builtins__':None}
        local_ctx = {
            'actor': actor,
            'target': target,
            'attribute_types' : all_attr_types,
        }
        local_ctx = dict(base_ctx.items() + local_ctx.items())
        exec self.compiled_script in global_ctx, local_ctx

action_types = {        
    'heal' : ActionType('heal','healed',''' 
actor.restrict('energy')
actor.add_effect('energy',-5)
target.add_effect('health',7)'''),
    'hurt' : ActionType('hurt','hurt', ''' 
actor.restrict('energy')
actor.add_effect('energy',-10)
target.add_effect('health',-10)'''),
    'steal' : ActionType('steal','stole', ''' 
actor.restrict('energy')
actor.add_effect('energy',-16)
actor.add_effect('health',+4)
target.add_effect('health',-8)'''),
    'last hurrah' : ActionType('last hurrah','last hurrahed', '''
energy = actor.attributes['energy'].last_value
health = actor.attributes['health'].last_value
actor.add_effect('energy',-energy)
target.add_effect('health',-(sqrt(100-health * energy)))'''),
    }


from shardedcounter import get_count, increment

class Action(db.Model):
    """ record the details of one person acting upon another
    """
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
        """ return the past tense of the action 
            should probably be stored with the action type
        """
        try:
            return action_types[self.action].past_tense
        except KeyError:
            return self.action

    def gen_age(self):
        """ generate a nice text string to describe how long ago the action happened
            TODO: should really move this to the client side
        """
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
        """ generates a key which can be used to sort entries in date order
            uses sharded counters to allow multiple actions in the same second
        
            be careful: the time format string below is designed to have 12 places to allow comparison of keys in order
            this will run out in the year 33679 - assuming the year 2038 problem is fixed :)
            to those that are maintaining the code in 33679CE: sorry! but i'm sure you'll be able to fix it and upgrade properly. 
            Say high to my descendants for me too!
        """
        seconds = date.strftime('%012s')
        count = increment('action_%s'%seconds)
        return '%s|%s' % (seconds,count)

    @classmethod
    def create(cls,actor,target,date,action,narration,actor_effects,target_effects):
        """ create a new action
        """
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
