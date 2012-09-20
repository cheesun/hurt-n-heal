from google.appengine.api import memcache
from google.appengine.datastore import entity_pb 
from google.appengine.ext import db

import json
from types import CodeType


class Serialized(object):
    def deserialize(self):
        raise NotImplementedError

# Protobuf objects/lists
class ProtoBufObj(Serialized):
    """ special type used to identify protobuf objects """
    def __init__(self, obj): 
        self.val = db.model_to_protobuf(obj).Encode()
        self.model_class = db.class_for_kind(obj.kind())
        # model class makes it unnecessary to import model classes
    def deserialize(self):
        return db.model_from_protobuf(entity_pb.EntityProto(self.val))

# Code Objects cant be pickled, but we can marshal them
# bewarned that marshalling output may vary between python versions
class MarshaledCodeObj(Serialized):
    """ special type used to identify code objects serialized with marshal """
    def __init__(self,data):
        self.val = marshal.dumps(data)
    def deserialize(self):
        return marshal.loads(self.val)

class SerializedList(Serialized):
    """ special type used to identify list containing serialized objects """
    def __init__(self, data):
        self.vals = []
        for obj in data:
            # if item is entity, protobuf it.
            if isinstance(obj, db.Model):
                self.vals.append(ProtoBufObj(obj))
            # if it's a code object, marshal it
            elif isinstance(obj, CodeType):
                self.vals.append(MarshaledCodeObj(obj))
            else:
                self.vals.append(obj)                    
    def deserialize(self):
        entities = []
        for obj in self.vals:
            try:
                entities.append(obj.deserialize())
            except AttributeError:
                entities.append(obj)
            return entities

# functions to (de)serialise objects to be stored in memcached
def to_binary(data):
    """ compresses entities or lists of entities for caching.

    Args: 
        data - arbitrary data input, on its way to memcache
    """ 
    if isinstance(data, db.Model):
        return ProtoBufObj(data)
    elif isinstance(data, CodeType):
        return MarshaledCodeObj(data)
    elif isinstance(data,list) and any(isinstance(x, db.Model) for x in data):
        # list of entities
        entities = []
        for obj in data:
            # if item is entity, protobuf it.
            if isinstance(obj, db.Model):
                entities.append(ProtoBufObj(obj))
            # if it's a code object, marshal it
            elif isinstance(obj, CodeType):
                entities.append(MarshaledCodeObj(obj))
            else:
                entities.append(obj)
        return SerializedList(entities)
    else: # return data as is, will be pickled by memcache library
        return data

def from_binary(data):
    """ decompresses entities or lists from cache.

    Args: 
        data - arbitrary data input from memcache
    """ 
    if isinstance(data, Serialized):
        return data.deserialize()
    else: # return data as is 
        return data


# higher level functions using memcached
import urllib2
import urllib

def cached_json_urlopen(url,duration=None):
    key = 'URL(%s)' % url
    result = from_binary(memcache.get(key))
    if not result:
        result = json.loads(urllib2.urlopen(url).read())        
        memcache.set(key,to_binary(result))
    return result

# 2 level cache
from lrucache import LRUCache, CacheKeyError
from random import random

class TwoLevelCache(object):
    '''
        uses both a simple LRUCache and Memcached
    '''
    def __init__(self,size=32000):
        self.cache = LRUCache(size=size)
  
    def get(self,key):
        try:
            # randomly go to memcached directly once in a while
            # this allows refreshing of the local instance cache from global
            if random < 0.001: # TODO: find the optimal value
                raise CacheKeyError
            #logging.warning('local cache hit for %s' % key)
            return self.cache[key]          
        except CacheKeyError:
            result = from_binary(memcache.get(key))
            if result:
                self.set(key,result)
            return result
      
    def set(self,key,value):
        self.cache[key] = value
        memcache.set(key,to_binary(value))
  
    def invalidate_cache(self,key):
        try:
            del self.cache[key]
        except CacheKeyError:
            pass
        memcache.delete(key)

# the module provides a cache at the instance level. 
# use this mainly for stuff you know wont change, as cache invalidation will not filter to other instances
instance_cache = TwoLevelCache()

def cached_get_by_key_name(model,key_name,duration=None):
    key = '%s(%s)' % (model.kind(),key_name)
    result = instance_cache.get(key)
    if not result:
        result = model.get_by_key_name(key_name)
        instance_cache.set(key,result)
    return result
    
    
    
