from google.appengine.ext import db

from models import Player, Attribute, AttributeType, Action, actions

from datetime import datetime
import parser
from math import *

class Alert(Exception):
    pass

def timedelta_to_seconds(td):
    return td.seconds + 86400.0 * td.days + td.microseconds / 1000000.0

class Calculator(object):
    '''
    
    '''
    ast_cache = {}
    ctx_cache = {}
    safe_functs = ['math','acos', 'asin', 'atan', 'atan2', 'ceil', 
                   'cos', 'cosh', 'degrees', 'e', 'exp', 'fabs', 
                   'floor', 'fmod', 'frexp', 'hypot', 'ldexp', 'log', 
                   'log10', 'modf', 'pi', 'pow', 'radians', 'sin', 
                   'sinh', 'sqrt', 'tan', 'tanh']
    base_ctx = dict([(k,locals().get(k,None)) for k in safe_functs])
    base_ctx['abs'] = abs
    base_ctx['min'] = min
    base_ctx['max'] = max
    
    @classmethod
    def fetch(cls,name):
        if name in cls.ctx_cache:
            return
        attr_type = AttributeType.get_by_key_name(name)
        cls.ast_cache[name] = parser.expr(attr_type.change_formula).compile()
        cls.ctx_cache[name] = {
            'name': attr_type.name,
            'description': attr_type.description,
            'min_value' : attr_type.min_value,
            'max_value' : attr_type.max_value,
            'default_value' : attr_type.default_value,
            'color' : attr_type.color,
            'order' : attr_type.order,
            }
            
    @classmethod
    def calculate(cls,name,ctx={}):
        if name not in cls.ast_cache:
            cls.fetch(name)
        attr_cache = cls.ctx_cache[name]
        value = eval(cls.ast_cache[name],{'__builtins__':None},dict(cls.base_ctx.items() + attr_cache.items()+ctx.items()))
        max_value = attr_cache['max_value']
        return {'name': name,
                 'value': value,
                 'color': attr_cache['color'],
                 'max_value': max_value,
                 'percentage': 100*value/max_value,           
                 'order': attr_cache['order'],
                }

class PlayerState(object):
    def __init__(self,player):
        self.player = player
        self.update()
    def update(self):
        self.attributes = {}
        attrs = Attribute.all().ancestor(self.player).fetch(1000)
        for attr in attrs:
            self.attributes[attr.name] = attr
        for name in ['health','energy']: # default attributes
            if name not in self.attributes:
                self.attributes[name] = Attribute.get_or_prepare(self.player,name)
    def snapshot(self,ref_time=None):
        output = {}
        if ref_time is None:
            ref_time = datetime.now()
        for attr in self.attributes:
            if not self.attributes[attr].is_saved():
                self.attributes[attr].latest_date = ref_time
            output[attr] = fast_forward(self.attributes[attr],ref_time)
        return output
        
        
def fast_forward(attribute,ref_time=None):
    ''' take an attribute value and fast forward any recovery to the ref_time
        ref_time defaults to now
    '''
    if ref_time is None:
            ref_time = datetime.now()
    elapsed = timedelta_to_seconds(ref_time - attribute.latest_date)
    if elapsed < 0:
        if elapsed > -1:
            elapsed = 0
        else:
            raise ValueError('attribute %s has a more recent timestamp (%s) than the reference time (%s)' % (attribute.name,attribute.latest_date,ref_time))
    ctx = {'initial_value': attribute.latest_value,
           'time_elapsed': elapsed,
            }
    return Calculator.calculate(attribute.name,ctx)


class Expando(object):
    ''' a utility class specifically for the purpose of adding attributes to instances
    '''
    pass


     
def get_current_info(player,now=None):
    ''' used in view   
        f(Player) --> (PlayerState,Action)
    '''
    if not now: 
        now = datetime.now()
    output = Expando()
    output.reference_time = now
    output.player = player
    output.attribute_state = sorted(PlayerState(player).snapshot(now).values(),key=lambda x: x['order'])
    output.last_action = Action.latest_action(player)
    return output




def perform_action(actor,target,action,scale,narration):
    ''' f(Player,Player,ActionType,Int) --> PlayerState    
    '''
    actor_effects, target_effects = actions[action]['effects']
    now = datetime.now()

    attr_types = {}
    for name,_ in actor_effects + target_effects:
        if name not in attr_types:
            attr_types[name] = AttributeType.get_by_key_name(name)
            Calculator.fetch(name)
    
    actor_state = PlayerState(actor)
    target_state = PlayerState(target)
    
    def take_effect(player,effects,types,player_state):
        output = []
        state = player_state.snapshot()
        for name,funct in effects:
            attr_type = attr_types[name]
            attr = Attribute.get_or_prepare(player,name,types[name])
            if not attr.is_saved():
                attr.latest_date = now
            current_value = fast_forward(attr,now)['value']
            delta = funct(scale)
            new_value = current_value + delta
            if new_value < attr_type.min_value:
                raise Alert('insufficient %s' % name)
            attr.latest_value = new_value
            attr.latest_date = now
            attr.put()
            sign = ''
            if delta > 0:
                sign = '+'
            output.append('%s%s %s' % (sign,int(delta),name))
        return ', '.join(output)
            
    actor_summary = db.run_in_transaction(take_effect,actor,actor_effects,attr_types,actor_state)
    target_summary = db.run_in_transaction(take_effect,target,target_effects,attr_types,target_state)
    
    Action.create(actor,target,now,action,narration,actor_summary,target_summary)



    

    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
