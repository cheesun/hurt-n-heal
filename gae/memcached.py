from google.appengine.api import memcache
from google.appengine.datastore import entity_pb 

import json

# Protobuf objects/lists
class ProtoBufObj():
  """ special type used to identify protobuf objects """
  def __init__(self, val, model_class): 
    self.val = val
    self.model_class = model_class 
    # model class makes it unnecessary to import model classes
  
class ProtoBufList():
  """ special type used to identify list containing protobuf objects """
  def __init__(self, vals):
    self.vals = vals

def makeProtoBufObj(obj):
  val = db.model_to_protobuf(obj).Encode()
  model_class =  db.class_for_kind(obj.kind())
  return ProtoBufObj(val, model_class) 

# functions to (de)serialise objects to be stored in memcached
def to_binary(data):
  """ compresses entities or lists of entities for caching.

  Args: 
        data - arbitrary data input, on its way to memcache
  """ 
  if isinstance(data, db.Model):
    # Just one instance
    return makeProtoBufObj(data)
  # if none of the first 5 items are models, don't look for entities
  elif isinstance(data,list) and any(isinstance(x, db.Model) for x in data):
    # list of entities
    entities = []
    for obj in data:
      # if item is entity, convert it.
      if isinstance(obj, db.Model):
       protobuf_obj = makeProtoBufObj(obj)
       entities.append(protobuf_obj)
      else:
       entities.append( obj )
    buffered_list = ProtoBufList(entities)
    return buffered_list
  else: # return data as is  
    return data

def from_binary(data):
  """ decompresses entities or lists from cache.

  Args: 
        data - arbitrary data input from memcache
  """ 
  if isinstance(data, ProtoBufObj):
    # Just one instance
    return db.model_from_protobuf(entity_pb.EntityProto(data.val))
  elif isinstance(data,ProtoBufList):
     entities = []
     for obj in data.vals:
       # if item is entity, convert it. 
       if isinstance(obj, ProtoBufObj):
         model_class = obj.model_class
         entities.append(db.model_from_protobuf(
         entity_pb.EntityProto(obj.val)) )
       else:
         entities.append( obj )    
    
     return entities
  else: # return data as is 
    return data

# higher level functions using memcached

import urllib2
import urllib

def cached_json_urlopen(url,duration=None):
    result = from_binary(memcache.get(url))
    if not result:
        result = json.loads(urllib2.urlopen(url).read())    
        memcache.set(url,to_binary(result))
    return result
