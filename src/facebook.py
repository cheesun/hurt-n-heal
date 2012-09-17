from memcached import cached_json_urlopen

def get_facebook_data(data,access_token):
    ''' this call gets the standard data associated with the logged in user
    '''
    mappings = { 
        'graph' : "https://graph.facebook.com/me?access_token=%s&fields=id,name,username,picture",
        'friends' : "https://graph.facebook.com/me/friends?access_token=%s",
        }
    info = cached_json_urlopen(mappings[data]%access_token)
    return info

def get_facebook_friends(access_token):
    ''' this call gets all friends and returns just the complete list (no paging information)
    '''
    url = "https://graph.facebook.com/me/friends?access_token=%s" % access_token
    friends = cached_json_urlopen(url)
    visited = set([url])
    output = friends['data']
    while 'next' in friends['paging']:
        nxt = friends['paging']['next']
        if nxt in visited:
            break
        friends = cached_json_urlopen(nxt)
        visited.add(nxt)
        data = friends['data']
        if data == []:
            break
        output.extend(data)
    return output
    
import base64    
import json
    
def decode_signed_req(data):
    ''' facebook includes a 'signed request'
        this function converts it into json
    '''
    data += "=" * (len(data) - 4) # add padding
    data = base64.urlsafe_b64decode(str(data))
    return json.loads(data)
