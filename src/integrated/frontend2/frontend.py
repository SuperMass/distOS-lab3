#!/usr/bin/env python

"""
Python source code - replace this with a description of the code and write the code below this text.
"""

# vim: tabstop=8 expandtab shiftwidth=4 softtabstop=4

import time
import threading
import SocketServer
from SimpleXMLRPCServer import SimpleXMLRPCServer,SimpleXMLRPCRequestHandler
#import SimpleXMLRPCServer
import os
import sys
import socket
import xmlrpclib
import frontend_config as cf
import re
import numpy as np

sys.path.append(os.getcwd())
import timeServer.timeServer as ts
import timeServer.time_config as tcf

win_per_num_request = cf.win_per_num_request
import heapq as hp
MAX_HEAP_SIZE = 1000
heap = []
c_time = 0
heap_size = 0
remove_count = 0

ack_num_dict = {}
aux_ack_dict = {}

process_num = 0

heap_lock = threading.Lock()
dict_lock = threading.Lock()

pid = cf.process_id
cluster_info = cf.cluster_info

myipAddress = cluster_info[str(pid)][0]
myport = cluster_info[str(pid)][1]

all_processes = []

# Threaded mix-in
class AsyncXMLRPCServer(SocketServer.ThreadingMixIn,SimpleXMLRPCServer): pass 

global client_object

global cache_mode # the system-wide cache_mode is retrieved from the backend server at the start of the frontend server
global client_dict
global client_dict_lock
client_dict = {}
client_dict_lock = threading.Lock()

global client_old_dict # not used in current implementation
global client_old_dict_lock # not used in current implementation

global cache_dict
global cache_dict_lock

global pull_period
global backend_s

global s_list
global URL_list

global pre_fe_status

client_old_dict = {}
client_old_dict_lock = threading.Lock()
cache_dict = {} # Cache key is RequestType-RequestContent (RequestType is 'Medal'/'Score'. For RequestType is 'Medal', RequestContent is 'Gauls'/'Romans', while for RequestType is 'Score', RequestContent is 'Curling'/'Skating'/'Skiing'. Thus the number of cache items is at most 5. It is easy to cache all of them, thus no replacement scheme is necessary. Nevertheless, you can maintain a priority queue besides the cache_dict (used both at the same time such both read and remove/add are efficient) to implement the LRU replacement scheme when the scale becomes much larger)
cache_dict_lock = threading.Lock()
pull_period = cf.pull_period

tally_board = [[0 for x in xrange(2)] for x in xrange(3)]
score_board = [[0 for x in xrange(4)] for x in xrange(3)]

team_name_dict = {"Gauls":0, "Romans":1}
medal_type_dict = {"Gold":0, "Silver":1, "Bronze":2}
event_type_dict = {"Curling":0, "Skating":1, "Skiing":2}

t_file = None
s_file = None
l_file = None
w_file = None

t_file_name = './log/tally_board.out'
s_file_name = './log/score_board.out'
l_file_name = './log/event_with_l_clock.out'
w_file_name = './log/winners_list.out'

#global sb_lock
#global output_lock
#global s_file_lock

class FirstList(tuple):
    def __lt__(self, other):
        if self[0:2] < other[0:2]:
            return True
        else:
            return False

def get_team_name_index(teamName):
	team_name_index = -1
	if team_name_dict.has_key(teamName): 	
		team_name_index = team_name_dict[teamName]
	return team_name_index

def get_medal_type_index(medalType):
	medal_type_index = -1
	if medal_type_dict.has_key(medalType): 	
		medal_type_index = medal_type_dict[medalType]
	return medal_type_index

def get_event_type_index(eventType):
	event_type_index = -1
	if event_type_dict.has_key(eventType): 	
		event_type_index = event_type_dict[eventType]
	return event_type_index

class RPCObject:
    def __init__(self):
        self.time_ip = tcf.cluster_info[str(tcf.process_id)][0]
        self.time_port = tcf.cluster_info[str(tcf.process_id)][1]
        self.time_proxy = xmlrpclib.ServerProxy("http://" + self.time_ip + ":" + str(self.time_port))

    def get_medal_tally(self, client_id, team_name = 'Gauls'):
        global pid
        global c_time

        result = self.__find_in_cache('Medal-'+team_name)
        if result == None:
            result = backend_s.getMedalTally(team_name)
            self.__update_cache('Medal-'+team_name, result)
        return (myipAddress+':'+str(myport), result)

    def get_score(self, client_id, event_type = 'Curling' ):
        result = self.__find_in_cache('Score-'+event_type)
        if result == None:
            result = backend_s.getScore(event_type)
            self.__update_cache('Score-'+event_type, result)
        result_return = result[:]
        return (myipAddress+':'+str(myport), result_return)

    def areYouMaster(self, dummy):
        """(lab3 funcs) called by bard for getting the addr of master process"""
        master_flag = ts.getIsMasterFlag()
        if master_flag == True:
            return 'OK'
        else:
            election_master_address, master_address = ts.getMasterAddress()
            master_ip, master_port = master_address
            if master_ip == '' or master_port == -1:
                result = ''
            else:
                result =  master_ip + ':' + str(master_port)
            return result
    
    def registerClient(self, claimed_fe_address, client_address):
        """(lab3 funcs) client re-distributed to here, because of the failure of its assigned frontend server, is added to client_dict"""
        global client_dict
        print 'registerClient due to fail of assigned front server: ', claimed_fe_address, ' ', client_address
        print 'my address is: ', myipAddress + ':' + str(myport)
        try:
            if claimed_fe_address != myipAddress + ':' + str(myport):
                client_dict_lock.acquire()
                if claimed_fe_address not in client_dict:
                    client_dict[claimed_fe_address] = set()
                client_dict[claimed_fe_address].add(client_address)
                client_dict_lock.release()
        except Exception as e:
            print e, ' at registerClient'
        return True

    def deregisterClient(self, claimed_fe_address, client_address):
        global client_dict
        """(lab3 funcs) deregister when the client process end"""
        print 'deregisterClient due to client exit: ', claimed_fe_address, ' ', client_address
        if claimed_fe_address != myipAddress + ':' + str(myport):
            client_dict_lock.acquire()
            if claimed_fe_address in client_dict and client_address in client_dict[claimed_fe_address]:
                client_dict[claimed_fe_address].remove(client_address)
                if len(client_dict[claimed_fe_address]) == 0:
                    del client_dict[claimed_fe_address]
            client_dict_lock.release()
        return True

    def incrementMedalTally(self, teamName, medalType):
        global s_list
        if not ts.getIsMasterFlag():
            result = backend_s.incrementMedalTally(teamName, medalType)
            return 'NO'
        if ts.getIsMasterFlag() and cache_mode == 1:
            print 'increase medal tally invalidation'
            for s in s_list:
                try:
                    s.invalidate_cache('Medal-'+teamName)
                except Exception as e:
                    print e
                    time.sleep(0.1)
                    try:
                        s.invalidate_cache('Medal-'+teamName)
                    except:
                        pass
        result = backend_s.incrementMedalTally(teamName, medalType)
        return result

    def setScore(self, eventType, score): # score is a list (score_of_Gauls, score_of_Romans, flag_whether_the_event_is_over)
        if not ts.getIsMasterFlag():
            result = backend_s.setScore(eventType, score)
            return 'NO'
        print self.time_ip, self.time_port
        print ts.getOffset()
        epoch_time = self.time_proxy.getOffset()
        #readable_time = time.strftime("%a, %d %b %Y %H:%M:%S +0000", time.localtime(epoch_time))
        score += [epoch_time]#[readable_time]

        print '****************'
        print '****************'
        print '****************'
        print 'set score: with time of epoch time format'
        print '****************'
        print '****************'
        print '****************'
        print score
        if ts.getIsMasterFlag() and cache_mode == 1:
            for s in s_list:
                try:
                    s.invalidate_cache('Score-'+eventType)
                except Exception as e:
                    print e
                    time.sleep(0.1)
                    try:
                        s.invalidate_cache('Score-'+eventType)
                    except:
                        pass
        return backend_s.setScore(eventType, score)

    def __find_in_cache(self, cache_key):
        """(lab3 funcs private) private function for locating cache_key, None if not found"""
        if cache_mode == -1: # do nothing if no cache strategy is used
            return None
        cache_dict_lock.acquire()
        cache_dict_tmp = cache_dict
        cache_dict_lock.release()
        if cache_key in cache_dict_tmp:
            return cache_dict_tmp[cache_key]
        else:
            return None

    def __update_cache(self, cache_key, value):
        """(lab3 funcs private) private function for updating value related for a given cache_key"""
        if cache_mode == -1:
            return
        cache_dict_lock.acquire()
        cache_dict[cache_key] = value        
        cache_dict_lock.release()

    def claim_client(client_uniq_id): # the function is not used in the final implementation, because we determine not let backend server know the status of clients
        client_old_dict_lock.acquire()
        client_old_dict[client_uniq_id] = True
        client_old_dict_lock.release()

        return backend_s.claim_client((client_uniq_id, True,))

def pull_update_cache():
    """(lab3 funcs module private) (local)pull cache functioning only in pull mode"""
    if cache_mode != 0:
        return False
    cache_dict_lock.acquire()
    for cache_key in cache_dict:
        if cache_key[0:5] == 'Score':
            value = backend_s.getScore(cache_key[6:len(cache_key)])
        else:
            value = backend_s.getMedalTally(cache_key[6:len(cache_key)])
        cache_dict[cache_key] = value        
    cache_dict_lock.release()
    return True

def record_request(request, l_time):
    """(RPC)lamport clock for implementing totally ordering: receive and record broadcast request"""
    global heap_lock
    global MAX_HEAP_SIZE
    global heap_size
    global heap
    global c_time

    ele = tuple(l_time)
    ele = FirstList(ele)
    flag = True
    heap_lock.acquire()
#    print 'record_request heap_lock acquired'
    if MAX_HEAP_SIZE <= heap_size:
        flag = False
    else:
        hp.heappush(heap, ele)
        if ele[1] != pid:
            c_time += 1 # suppose the request sent to self is received immediately!
        heap_size += 1

    heap_lock.release()
#    print 'record_request heap_lock released'
    return flag

def send_ack(l_time, pro_id):
    """(RPC)lamport clock for implementing totally ordering: send out ACK for received broadcast request"""
    global ack_num_dict
    global aux_ack_dict
    global dict_lock

    l_time = tuple(l_time[0:2])
# l_time is asserted a tuple

    dict_lock.acquire()
    if l_time in ack_num_dict:
        ack_num_dict[l_time] += 1
        aux_ack_dict[l_time] += [pro_id]
    else:
        ack_num_dict[l_time] = 1
        aux_ack_dict[l_time] = [pro_id]
    dict_lock.release()
    return True

def check_alive():
    """(RPC) trivial function: check whether the frontend server is alive """
    return True

class PullThread(threading.Thread):
    """cache pull mode background thread"""
    def __init__(self):
        threading.Thread.__init__(self)
    def run(self):
        while True:
            time.sleep(pull_period)
            try:
                pull_update_cache()
            except:
                pass
            continue

class HeapThread(threading.Thread):
    """background thread for implementing totally ordering"""
    def __init__(self):
        threading.Thread.__init__(self)
    def run(self):
        global heap_lock
        global client_object
        global heap_size
        global heap
        global ack_num_dict
        global aux_ack_dict
        global process_num
        global remove_count
        global win_per_num_request
        global pid
        global s_list

        have_sent_ack = set()
        ExpireCount = 3 # 3 seconds
        flag_count = 0

        ele_pre = None

        while True:
            time.sleep(1+np.random.rand()*2)
            heap_lock.acquire()
            if heap_size == 0:
                print 'nothing'
                pass
            else:
                time.sleep(0.1)
#                print 'sent ack list: ', list(have_sent_ack)
                for l_time in heap:
                    l_time = tuple(l_time)
                    if l_time[0:2] not in have_sent_ack:
                        have_sent_ack.add(l_time[0:2])
                        for s in s_list:
                            try:
                                s.send_ack(l_time, pid)
                            except Exception as e: # retransmission, assume that when this happens, the failed RPC does not affect the status of corresponding server
                                print 'send ack error: ', e
                                try:
                                    s.send_ack(l_time, pid)
                                except:
                                    pass
                dict_lock.acquire()
                try:
                    heap_tmp = tuple(heap[0])
                    print '++++1', heap_tmp

                    if heap_tmp[0:2] in ack_num_dict:
                        print '++++2', ack_num_dict[heap_tmp[0:2]]
                        print '++++3', aux_ack_dict[heap_tmp[0:2]]
                    else:
                        print '++++2,3', ' no dict element'
                    print 'ele_pre', ele_pre
                    print 'ele_cur', heap_tmp[0:2]
                    print 'flag_count', flag_count
                    if ele_pre == heap_tmp[0:2]:
                        flag_count += 1
                    else:
                        flag_count = 0

                    if flag_count >= ExpireCount: # timeout, remove it from the heap
                        if heap_tmp[0:2] in ack_num_dict:
                            del ack_num_dict[heap_tmp[0:2]]
                        ele = hp.heappop(heap)
                        print '****', ele
                        heap_size -= 1
                        flag_count = 0

                    if heap_size > 0:
                        heap_tmp = tuple(heap[0])
                        ele_pre = heap_tmp[0:2]
                    else:
                        ele_pre = None

                    while heap_size > 0:
                        heap_tmp = tuple(heap[0])
                        if heap_tmp[0:2] in ack_num_dict and ack_num_dict[heap_tmp[0:2]] >= process_num:
                            del ack_num_dict[heap_tmp[0:2]]
                            ele = hp.heappop(heap)
                            print '----', ele
                            remove_count += 1
                            heap_size -= 1

                            with open(l_file_name, 'a') as l_file :
                                l_file.write(str((ele[0],ele[2])) + '\n')
                            if remove_count % win_per_num_request == 0:
                                with open(w_file_name, 'a') as w_file :
                                    w_file.write(str(ele[2]) + '\n')
                        else:
                            break
                except Exception as e:
                    print 'wzd'
                    print e
                dict_lock.release()
            heap_lock.release()
            print 'heap thread'

def invalidate_cache(cache_key):
    """each time an update happened on master front server by the bard, the related cache item is invalidated"""
    if cache_mode == -1:
        return False
    cache_dict_lock.acquire()
    if cache_key in cache_dict:
        del cache_dict[cache_key]
    cache_dict_lock.release()
    return True

def invalidate_whole_cache():
    """(lab3 funcs module private) each time a master is re-elected, the whole cache is invalidated"""
    if cache_mode == -1:
        return False
    print 'whole cache invalidated'
    cache_dict_lock.acquire()
    cache_dict.clear()
    cache_dict_lock.release()
    return True

class ServerThread(threading.Thread):
    """a RPC server listening to push request from the server of the whole system"""
    def __init__(self, port):
        threading.Thread.__init__(self)
        self.port = port

        self.localServer = AsyncXMLRPCServer(('', port), SimpleXMLRPCRequestHandler) #SimpleXMLRPCServer(('', port))
        self.localServer.register_instance(RPCObject())

        self.localServer.register_function(record_request, 'record_request')
        self.localServer.register_function(check_alive, 'check_alive')
        self.localServer.register_function(send_ack, 'send_ack')
        self.localServer.register_function(invalidate_cache, 'invalidate_cache')
        self.localServer.register_function(invalidate_whole_cache, 'invalidate_whole_cache')
    def run(self):
        self.localServer.serve_forever()

class FeScanThread(threading.Thread):
    """(lab3 thread background) Background thread: checking whether a fe (short for frontend server) is recovered from disconnected, and in that case, notify the corresponding clients"""
    def __init__(self, scan_interval):
        threading.Thread.__init__(self)
        self.scan_interval = scan_interval
    def run(self):
        global pre_fe_status
        global client_dict

        while True:
            time.sleep(self.scan_interval)
            for i in range(len(s_list)):
                try:
                    s_list[i].check_alive()
                    if not pre_fe_status[i]:
                        print 'reconnect clients to their (revived) original frontend server: '
                        print URL_list[i]
                        client_dict_lock.acquire()
                        print client_dict
                        if URL_list[i] in client_dict:
                            print 'related clients are:'
                            print list(client_dict[URL_list[i]])
                            for client in list(client_dict[URL_list[i]]):
                                try:
                                    x = 'abc'
                                    proxy_tmp = xmlrpclib.ServerProxy('http://'+client)
                                    proxy_tmp.change_back_proxy()
                                except Exception as e:
                                    print e
                                    continue
                        client_dict_lock.release()

                    pre_fe_status[i] = True
                except Exception as e:
                    pre_fe_status[i] = False

if __name__ == "__main__":
    try:
        l_file = open(l_file_name, 'w')
        l_file.close()
        w_file = open(w_file_name, 'w')
        w_file.close()
    except Exception as e:
        print e
        sys.exit(1)

    # backend server ip and port
    remote_host_name = cf.server_ip
    remote_port = cf.server_port

        
    URL = "http://" + remote_host_name + ":" + str(remote_port)
    backend_s = xmlrpclib.ServerProxy(URL)
    print 'Backend Server URL:', URL

    while True:
        try:
            cache_mode = backend_s.get_cache_mode()
            break
        except Exception as e:
            print e
            print 'wait the backend server to start'
            time.sleep(2)
    
    server = ServerThread(myport)
    server.daemon = True; # allow the thread exit right after the main thread exits by keyboard interruption.
    server.start() # The server is now running

    # cluster of all frontend servers
    for i in cluster_info:
        all_processes.append((cluster_info[i][0], cluster_info[i][1], int(i)))
    process_num = len(all_processes)

    pre_fe_status = []
    URL_list = []
    s_list = []
    for process in all_processes:
        URL = "http://" + process[0] + ":"+ str( process[1] )
        print URL
        pre_fe_status.append(False)
        URL_list.append(process[0]+':'+str(process[1]))
        s_list.append(xmlrpclib.ServerProxy(URL))

    # set up time server
    ts.SetupServer((myipAddress, myport), s_list) # it is just used for master selection

    # it is supposed the two frontend servers should both start normally
    while True:
        try:
            for i in range(len(all_processes)):
                print i
                s_list[i].check_alive()
                pre_fe_status[i] = True
            time.sleep(2)
            break
        except Exception as e:
            print e
            print 'waiting...'   
            time.sleep(2)
            continue

    print 'all frontend servers have started'

    scan_interval = 2
    fe_thread = FeScanThread(scan_interval)
    fe_thread.daemon = True
    fe_thread.start()

    if cache_mode == 0:
        pull_thread = PullThread()
        pull_thread.daemon = True
        pull_thread.start()

    while True:
        time.sleep(5)
