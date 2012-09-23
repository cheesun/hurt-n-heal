from google.appengine.ext import db

from models import Player, Attribute, AttributeType, Action, action_types, base_ctx
from caching import cached_get_by_key_name, instance_cache

from datetime import datetime
import parser
from math import *

class Alert(Exception):
    pass

def timedelta_to_seconds(td):
    return td.seconds + 86400.0 * td.days + td.microseconds / 1000000.0   
    
class Thespian(object):
    ''' Instantiate one of these to play out the effects of an action
        Thespian.add_effect() queues up the effects of that action
        Thespian.run_effects_at() saves all queued effects to the datastore
    '''
    def __init__(self,player):
        self.player = player
        
        self.attribute_types = {}
        cache_key = 'AttributeType.all()'
        all_attr_types = instance_cache.get(cache_key)
        if not all_attr_types:
            all_attr_types = AttributeType.all().fetch(1000)
            instance_cache.set(cache_key,all_attr_types)
        for attribute_type in all_attr_types:
            self.attribute_types[attribute_type.name] = attribute_type
            
        self.update()
        
    def update(self):
        self.has_run = False
        self.attributes = {}
        self.effects = {}
        self.restricted = set()
        attrs = Attribute.all().ancestor(self.player).fetch(1000)
        for attr in attrs:
            self.attributes[attr.name] = attr
            if attr not in self.attribute_types:
                self.attribute_types[attr.name] = cached_get_by_key_name(AttributeType,attr.name)
        # if you're missing default attributes, create them
        for name in ['health','energy']: 
            if name not in self.attributes:
                self.attributes[name] = Attribute.get_or_prepare(self.player,name)
                if name not in self.attribute_types:
                    self.attribute_types[name] = cached_get_by_key_name(AttributeType,name)

    def fast_forward(self,attribute,ref_time=None):
        """ take an attribute value and fast forward any recovery to the ref_time
            ref_time defaults to now
        """
        attr_name = attribute.name
        
        if ref_time is None:
                ref_time = datetime.now()
        elapsed = timedelta_to_seconds(ref_time - attribute.latest_date)
        if elapsed < 0:
            if elapsed > -1:
                elapsed = 0
            else:
                raise ValueError('attribute %s has a more recent timestamp (%s) than the reference time (%s)' % (attr_name,attribute.latest_date,ref_time))

        attribute_type = self.attribute_types[attr_name]
        default = attribute_type.default_value
        latest_value = attribute.latest_value
        global_ctx = {'__builtins__':None}
        local_ctx = {'actor':self}
        local_ctx = dict(local_ctx.items() + base_ctx.items())
        if latest_value < default :
            new_value = min(latest_value + elapsed * eval(attribute_type.recovery,global_ctx,local_ctx), default)
        elif latest_value > default :
            new_value = max(latest_value - elapsed * eval(attribute_type.decay,global_ctx,local_ctx), default)
        else:
            new_value = latest_value
                
        return {'name': attr_name,
                 'value': new_value,
                 'color': attribute_type.color,
                 'max_value': attribute_type.max_value,
                 'percentage': 100*new_value/attribute_type.max_value,           
                 'order': attribute_type.order,}
                
                
    def snapshot(self,ref_time=None):
        output = {}
        if ref_time is None:
            ref_time = datetime.now()
        for attr in self.attributes:
            if not self.attributes[attr].is_saved():
                self.attributes[attr].latest_date = ref_time
            output[attr] = self.fast_forward(self.attributes[attr],ref_time)
        return output
        
    def restrict(self,attr):
        """ tells the Thespian to fail if this action would cause this 
            attribute to fall out of bounds """
        self.restricted.add(attr)
        
    def add_effect(self,attr_name,amount):
        try:
            self.effects[attr_name] += amount
        except KeyError:
            self.effects[attr_name] = amount
            self.attribute_types[attr_name] = cached_get_by_key_name(AttributeType,attr_name)
            
    def run_effects_at(self,ref_time):
        if self.has_run:
            raise Alert('This Thespian has already completed running')
        for name,delta in self.effects.items():
            attr_type = self.attribute_types[name]
            # create new attributes if you are acted upon by them
            attr = Attribute.get_or_prepare(self.player,name,attr_type)
            if not attr.is_saved():
                attr.latest_date = ref_time
            current_value = self.fast_forward(attr,ref_time)['value']
            new_value = current_value + delta
            if attr_type in self.restricted and new_value < attr_type.min_value or new_value > attr_type.max_value:
                raise Alert('%s has insufficient %s' % (self.player.nickname,name))
            new_value = min(max(new_value,attr_type.min_value),attr_type.max_value)
            attr.latest_value = new_value
            attr.latest_date = ref_time
            attr.put()
        self.has_run = True
    
    def effect_summary(self):
        output = []
        for attr in sorted(self.effects.keys(),key=lambda x:self.attribute_types[x].order):
            delta = self.effects[attr]
            if delta > 0:
                sign = '+'
            else:
                sign = ''
            output.append('%s%s %s' % (sign,int(delta),attr))
        return ' '.join(output)


            
def act(actor,target,action,narration):
    a = Thespian(actor)
    t = Thespian(target)
    action_types[action].run_script(a,t)
    now = datetime.now()
    db.run_in_transaction(a.run_effects_at,now)
    if target.key().name() != actor.key().name():
        db.run_in_transaction(t.run_effects_at,now)
    Action.create(actor,target,now,action,narration,a.effect_summary(),t.effect_summary())
    
def get_current_info(player,now=None):
    """ used in view   
        f(Player) --> (PlayerState,Action)
    """
    if not now: 
        now = datetime.now()
    return {
        'reference_time': now,
        'player': player,
        'attribute_state': sorted(Thespian(player).snapshot(now).values(),key=lambda x: x['order']),
        'last_action': Action.latest_action(player)    
        }
    
