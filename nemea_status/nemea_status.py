#!/usr/bin/env python
# Needs Python 3.x or Python 2.6+
from __future__ import print_function
import sys
import random
import time
import subprocess
import json

from flask import Flask, request, render_template, g, jsonify

app = Flask(__name__)

app.jinja_env.trim_blocks = True
app.jinja_env.lstrip_blocks = True


# *** Load config ***
config_file = '/etc/nemea/nemea_status.conf'
# Initialize cfg with defaults
cfg = {
    'supervisor_cli': '/usr/bin/nemea/supervisor_cli',
    'supervisor_socket': '/var/run/nemea-supervisor/nemea-supervisor.sock',
    'links': [],
}
# Load and parse config file
try:
    with open(config_file) as f:
        for n,line in enumerate(f):
            if line.lstrip().startswith('#') or not line.strip(): # skip comments and empty lines
                continue
            key, val = map(str.strip, line.split('=', 1))
            if key == 'link': # parse link specification and append to the list of links
                cfg['links'].append(tuple(map(str.strip, val.split('|', 1))))
            else:
                cfg[key] = val
except IOError as e:
    print("Warning: Can't load config file (using defaults): {}".format(str(e)), file=sys.stderr)
except Exception as e:
    print("Error in config file on line {}.".format(n+1), file=sys.stderr)
    sys.exit(1)

SUP_PATH = cfg['supervisor_cli']
SUP_SOCK_PATH = cfg['supervisor_socket']

MUNIN_BASE = cfg.get('munin_base', '')

LINKS = cfg['links']

# TODO: detection of topology change (in Javascript, ifcs returned from _stats don't match the ones loaded -> tell user to reload page)

#####

# Backport of subprocess.check_output to Python 2.6
# Taken from http://stackoverflow.com/questions/28904750/python-check-output-workaround-in-2-6
if "check_output" not in dir( subprocess ): # duck punch it in!
    def check_output(*popenargs, **kwargs):
        r"""Run command with arguments and return its output as a byte string.

        Backported from Python 2.7 as it's implemented as pure python on stdlib.

        >>> check_output(['/usr/bin/python', '--version'])
        Python 2.6.2
        """
        process = subprocess.Popen(stdout=subprocess.PIPE, *popenargs, **kwargs)
        output, unused_err = process.communicate()
        retcode = process.poll()
        if retcode:
            cmd = kwargs.get("args")
            if cmd is None:
                cmd = popenargs[0]
            error = subprocess.CalledProcessError(retcode, cmd)
            error.output = output
            raise error
        return output
    subprocess.check_output = check_output


###############
# Topology

def get_topology():
    cmd_and_args = [SUP_PATH, "-s", SUP_SOCK_PATH, "-i"]
    #print(' '.join(cmd_and_args))
    try:
        out = subprocess.check_output(cmd_and_args, stderr=subprocess.STDOUT)
        if isinstance(out, bytes):
            out = out.decode() # in Py3, output of check_output is of type bytes
        #print(out)
    except subprocess.CalledProcessError as e:
        return {
            'error': 'callerror',
            'cmd': ' '.join(cmd_and_args),
            'code': e.returncode,
            'output': e.output,
        }
    try:
        return sorted(json.loads(out).items(), key=lambda mod: mod[1]['idx'])
    except ValueError:
        return {
            'error': 'invalidjson',
            'cmd': ' '.join(cmd_and_args),
            'output': out,
        }


###############
# Counter stats

def get_indxed_key(d, prefix):
    i = 0
    while prefix + str(i) in d:
        i += 1
    return prefix + str(i)

def get_stats():
    cmd_and_args = [SUP_PATH, "-s", SUP_SOCK_PATH, "-x"]
    #print(' '.join(cmd_and_args))
    try:
        out = subprocess.check_output(cmd_and_args, stderr=subprocess.STDOUT)
        if isinstance(out, bytes):
            out = out.decode() # in Py3, output of check_output is of type bytes
        #print(out)
    except subprocess.CalledProcessError as e:
        return {
            'error': 'callerror',
            'cmd': ' '.join(cmd_and_args),
            'code': e.returncode,
            'output': e.output,
        }
    # Parse output
    try:
        res = {}
        j = json.loads(out)
        for module, data in j.items():
            res[module + '_mem'] = data['MEM-vms']/1000
            res[module + '_cpu'] = data['CPU-u'] + data['CPU-s']
            for inpt in data['inputs']:
                res[get_indxed_key(res, module+'_INIFC')] = inpt['messages']
            for otpt in data['outputs']:
                ifcid = get_indxed_key(res, module+'_OUTIFC')
                res[ifcid] = otpt['sent-msg']
                res[ifcid + '_dropped'] = otpt['drop-msg']
        return res
    except Exception:
        raise
        return {
            'error': 'format',
            'cmd': ' '.join(cmd_and_args),
            'output': out,
        }

        

# ***** Main page *****
@app.route('/')
def main():
    topology = get_topology()
    return render_template('nemea_status.html', topology=topology, **globals())


# ***** Get statistics via AJAX request *****
@app.route('/_stats')
def events():
    stats = get_stats()
    #time.sleep(1)
    return jsonify(stats=stats)


if __name__ == "__main__":
    app.run(host='0.0.0.0',debug=True)

