process_id = 1 # client starts from 3. 1, and 2 are frontend servers

cluster_info = {
        '1':('127.0.0.1', 8005,), # choose the frontserver port equal to its corresponding timeServer port minus port_diff
        '2':('127.0.0.1', 8006,),
		}

server_ip = '127.0.0.1'
server_port = 8000
pull_period = 1 # unit is second, it works only when pull mode is chosen by the backend server
port_diff = 95

win_per_num_request = 100
