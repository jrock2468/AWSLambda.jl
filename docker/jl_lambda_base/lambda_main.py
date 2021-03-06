#==============================================================================#
# lambda_main.py
#
# AWS Lambda wrapper for Julia.
#
# See http://docs.aws.amazon.com/lambda/latest/dg/API_Reference.html
#
# Copyright OC Technology Pty Ltd 2014 - All rights reserved
#==============================================================================#


from __future__ import print_function

import subprocess
import os
import json
import time
import select


# Get CPU type for logging...
# See https://forums.aws.amazon.com/thread.jspa?messageID=804338
def cpu_model():
   with open("/proc/cpuinfo") as f:
       for l in f:
           if "model name" in l:
               return l.split(":")[1].strip()

cpu_model_name = cpu_model()


# Set Julia package directory...
name = os.environ['AWS_LAMBDA_FUNCTION_NAME']
root = os.environ['LAMBDA_TASK_ROOT']
os.environ['HOME'] = '/tmp/'
os.environ['JULIA_PKGDIR'] = root + '/julia'
os.environ['JULIA_LOAD_PATH'] = root
os.environ['PATH'] += ':' + root + '/bin'


# Load configuration...
execfile('lambda_config.py')


# Start Julia interpreter...
julia_proc = None
def start_julia():
    global julia_proc
    cmd = [root + '/bin/julia', '-i', '-e',
           'using module_' + name + '; '                                       \
         + 'using AWSLambdaWrapper; '                                          \
         + 'AWSLambdaWrapper.main(module_' + name + ');']
    print(' '.join(cmd))
    julia_proc = subprocess.Popen(cmd, stdin=subprocess.PIPE,
                                       stdout=subprocess.PIPE,
                                       stderr=subprocess.STDOUT)


def main(event, context):

    print(cpu_model_name)

    # Clean up old return value files...
    if os.path.isfile('/tmp/lambda_out'):
        os.remove('/tmp/lambda_out')

    # Store input in tmp file...
    with open('/tmp/lambda_in', 'w') as f:
        json.dump({
            'event': event,
            'context': context.__dict__
        }, f, default=lambda o: '')

    # Start or restart the Julia interpreter as needed...
    global julia_proc
    if julia_proc is None or julia_proc.poll() is not None:
        start_julia()

    # Tell the Julia interpreter that input is ready...
    julia_proc.stdin.write('\n')
    julia_proc.stdin.flush()

    # Calculate execution time limit...
    time_limit = time.time() + context.get_remaining_time_in_millis()/1000.0
    time_limit -= 5.0

    # Wait for output from "julia_proc"...
    out = ''
    complete = False
    while time.time() < time_limit:
        ready = select.select([julia_proc.stdout], [], [],  
                              time_limit - time.time())
        if julia_proc.stdout in ready[0]:
            line = julia_proc.stdout.readline()
            if line == '\0\n':
                complete = True
                break
            if line == '':
                message = 'EOF on Julia stdout!'
                if julia_proc.poll() != None:
                    message += (' Exit code: ' + str(julia_proc.returncode))
                raise Exception(message + '\n' + out + cpu_model_name)
            print(line, end='')
            out += line

    # Terminate Julia process on timeout...
    if not complete:
        print('Timeout!')
        out += 'Timeout!\n'
        p = julia_proc
        julia_proc = None
        p.terminate()
        while p.poll() == None:
            ready = select.select([p.stdout], [], [], 1)
            if p.stdout in ready[0]:
                line = p.stdout.readline()
                print(line, end='')
                out += line

    # Check exit status...
    if julia_proc == None or julia_proc.poll() != None:
        if error_sns_arn != '':
            subject = 'Lambda ' + ('Error: ' if complete else 'Timeout: ')     \
                    + name + json.dumps(event, separators=(',',':'))
            error = name + '\n'                                                \
                  + context.invoked_function_arn + '\n'                        \
                  + context.log_group_name + context.log_stream_name + '\n'    \
                  + json.dumps(event) + '\n\n'                                 \
                  + out
            import boto3
            try:
                boto3.client('sns').publish(TopicArn=error_sns_arn,
                                            Message=error,
                                            Subject=subject[:100])
            except Exception:
                pass

        raise Exception(out + cpu_model_name)

    # Return content of output file...
    if os.path.isfile('/tmp/lambda_out'):
        with open('/tmp/lambda_out', 'r') as f:
            return {'jl_data': f.read(), 'stdout': out}
    else:
        return {'stdout': out}



#==============================================================================#
# End of file.
#==============================================================================#
