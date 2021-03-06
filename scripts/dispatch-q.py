#!/usr/bin/env python

# Wrapper for fig's simple workqueue system.
# https://github.com/percyliang/fig/blob/master/bin/q
# Each command outputs JSON.

import sys, os, json, re
import subprocess
import argparse

def get_output(command):
    print >>sys.stderr, 'dispatch-q.py: ' + command,
    output = subprocess.check_output(command, shell=True)
    print >>sys.stderr, ('=> %d lines' % len(output.split('\n')))
    return output

if len(sys.argv) <= 1:
    print 'Usage:'
    print '  start [--request-time <seconds>] [--request-memory <bytes>] <script>'
    print '    => {handle: ...}'
    print '  info <handle>*'
    print '    => {..., infos: [{handle: ..., hostname: ..., memory: ...}, ...]}'
    print '  kill <handle>'
    print '    => {handle: ...}'
    print '  cleanup <handle>'
    print '    => {handle: ...}'
    sys.exit(1)

mode = sys.argv[1]
if mode == 'start':
    parser = argparse.ArgumentParser()
    parser.add_argument('--username', type=str, help='user who is running this job')
    parser.add_argument('--request_time', type=float, help='request this much computation time (in seconds)')
    parser.add_argument('--request_memory', type=float, help='request this much memory (in bytes)')
    parser.add_argument('--request_cpus', type=int, help='request this many CPUs')
    parser.add_argument('--request_gpus', type=int, help='request this many GPUs')
    parser.add_argument('--request_queue', type=int, help='submit job to this queue')
    parser.add_argument('--request_priority', type=int, help='priority of this job (higher is more important)')
    parser.add_argument('--share_working_path', help='whether we should run the job directly in the script directory', action='store_true')
    parser.add_argument('script', type=str, help='script to run')
    args = parser.parse_args(sys.argv[2:])

    resource_args = ''
    if args.request_time != None:
        resource_args += ' -time %ds' % int(args.request_time)

    # Note: if running in docker container, this doesn't do anything since q
    # doesn't know about docker, and the script is not the thing actually
    # taking memory.
    if args.request_memory != None:
        resource_args += ' -mem %dm' % int(args.request_memory / (1024*1024)) # convert to MB

    if args.request_priority != None:
        resource_args += ' -priority -- %d' % (-args.request_priority)  # Note: need to invert

    if args.share_working_path:
        # Run directly in the same directory.
        resource_args += ' -shareWorkingPath true'
        launch_script = args.script
    else:
        # q will run the script in a <scratch> directory.
        # args.script: <path>/<uuid>.sh
        # Tell q to copy everything related <uuid> back.
        orig_path = os.path.dirname(args.script)
        uuid = os.path.basename(args.script).split('.')[0]
        resource_args += ' -shareWorkingPath false'
        resource_args += ' -inPaths %s/%s*' % (orig_path, uuid)
        resource_args += ' -realtimeInPaths %s/%s.action' % (orig_path, uuid)  # To send messages (e.g., kill)
        resource_args += ' -outPath %s' % orig_path
        resource_args += ' -outFiles full:%s*' % uuid
        # Need to point to new script
        if args.script.startswith('/'):
            # Strip leading / to make path relative.
            # This way, q will run the right script.
            os.chdir('/')
            launch_script = args.script[1:]
        else:
            launch_script = args.script

    stdout = get_output('q%s -add bash %s use_script_for_temp_dir' % (resource_args, launch_script))
    m = re.match(r'Job (J-.+) added successfully', stdout)
    handle = m.group(1) if m else None
    response = {'raw': stdout, 'handle': handle}
elif mode == 'info':
    handles = sys.argv[2:]  # If empty, then get info about everything
    list_args = ''
    if len(handles) > 0:
        list_args += ' ' + ' '.join(handles)
    stdout = get_output('q -list%s -tabs' % list_args)
    response = {'raw': stdout}
    # Example output:
    # handle    worker              status  exitCode   exitReason   time    mem    disk    outName     command
    # J-ifnrj9  mazurka-37 mazurka  done    0          ....         1m40s   1m     -1m                 sleep 100
    infos = []
    for line in stdout.strip().split("\n"):
        if line == '': continue
        tokens = line.split("\t")
        info = {'handle': tokens[0]}

        hostname = tokens[1]
        if hostname != '':
            info['hostname'] = hostname.split()[-1]  # worker => hostname

        info['state'] = {'running': 'running'}.get(tokens[2], 'queued')

        exitcode = tokens[3]
        if exitcode != '':
            info['exitcode'] = int(exitcode)

        exitreason = tokens[4]
        if exitreason != '':
            info['exitreason'] = exitreason

        time = tokens[5]
        if time:
            info['time'] = int(time)

        memory = tokens[6]
        if memory:
            info['memory'] = int(memory) * 1024 * 1024  # Convert to bytes

        infos.append(info)
    response['infos'] = infos
elif mode == 'kill':
    handle = sys.argv[2]
    response = {
        'handle': handle,
        'raw': get_output('q -kill %s' % handle)
    }
elif mode == 'cleanup':
    handle = sys.argv[2]
    response = {
        'handle': handle,
        'raw': get_output('q -del %s' % handle)
    }
else:
    print 'Invalid mode: %s' % mode
    sys.exit(1)

print json.dumps(response)
