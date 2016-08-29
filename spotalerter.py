#!/usr/bin/env python

#####################
# Spot Alerter
# Copyright (c) 2016 Joshua Blake, Krista Blake
#####################
# Check AWS EC2 spot price for a specific machine type.
# Includes price threshold with SMS alert.
#####################
# Setup:
#####################
# pip install boto3
# See also https://github.com/boto/boto3
# pip install twilio
# pip install pyyaml
#
# Create ~/.aws/credentials with the next three lines:
#[default]
#aws_access_key_id = YOUR_KEY
#aws_secret_access_key = YOUR_SECRET
#
# See http://docs.aws.amazon.com/AWSSimpleQueueService/latest/SQSGettingStartedGuide/AWSCredentials.html
# for how to retrieve your access key and secret key
#
# Create ~/.aws/config with the next two lines:
#[default]
#region=us-west-2
#
# Create ~/.twilio/twilio_config.yaml that has the next two lines in it:
#TwilioAccount: AC...
#TwilioAuthToken: ...
#FromNumber: "+15405551234"
#ToNumber: "+17035554321"
#
# Your Twilio token is available from Twilio Console: https://www.twilio.com/console
# FromNumber should be the Twilio SMS-enabled number you reserved.
#   See https://www.twilio.com/console/phone-numbers/incoming
# ToNumber should be your personal cell number, ideally the one with which
# you verified your Twilio account.
#
#####################
# Usage:
#####################
# Run the script with no options to get current price
# Run with -h for help
#####################

import sys
import argparse
import time
import datetime
import os

import boto3
from twilio.rest import TwilioRestClient
import yaml

#modify these variables if you are interested in a different product price
instanceType = 'r3.8xlarge'
availabilityZone = 'us-west-2b'
productDescription = 'Linux/UNIX'

def load_twilio_credentials():
    filename = os.path.expanduser('~') + "/.twilio/twilio_config.yaml"
    stream = file(filename, 'r')
    creds = yaml.load(stream)
    twilio_account = creds.get('TwilioAccount', "")
    if len(twilio_account) == 0:
        print "Error: TwilioAccount value not found in " + filename
        quit(code=1)
    twilio_auto_token = creds.get('TwilioAuthToken', "")
    if len(twilio_auto_token) == 0:
        print "Error: TwilioAuthToken value not found in " + filename
        quit(code=1)
    from_number = creds.get('FromNumber', "")
    if len(from_number) == 0:
        print "Error: FromNumber value not found in " + filename
        quit(code=1)
    to_number = creds.get('ToNumber', "")
    if len(to_number) == 0:
        print "Error: ToNumber value not found in " + filename
        quit(code=1)

    return (twilio_account, twilio_auto_token, from_number, to_number)

def check_price(ec2, instanceType, availabilityZone, productDescription):
    resp = ec2.describe_spot_price_history(
    #StartTime and EndTime the same seems to give a single most recent price
        StartTime=datetime.datetime.utcnow(),
        EndTime=datetime.datetime.utcnow(),
        InstanceTypes=[instanceType],
        AvailabilityZone=availabilityZone,
        ProductDescriptions=[productDescription],
        MaxResults=1
    )
    #resp looks like:
    #{u'NextToken': '', u'SpotPriceHistory': [{u'Timestamp': datetime.datetime(2016, 8, 29, 3, 17, 38, tzinfo=tzutc()), u'ProductDescription': 'Linux/UNIX', u'InstanceType': 'r3.8xlarge', u'SpotPrice': '0.925400', u'AvailabilityZone': 'us-west-2b'}], 'ResponseMetadata': {'HTTPStatusCode': 200, 'RequestId': '55a0f722-f73e-48ae-b15e-ae5a92f7f182', 'HTTPHeaders': {'transfer-encoding': 'chunked', 'vary': 'Accept-Encoding', 'server': 'AmazonEC2', 'content-type': 'text/xml;charset=UTF-8', 'date': 'Mon, 29 Aug 2016 03:20:19 GMT'}}}

    sph = resp.get('SpotPriceHistory', [])
    if len(sph) == 0:
        print "Warning: AWS response: SpotPriceHistory field not available: " + str(resp)
        return ()
    price_str = sph[0].get('SpotPrice', "None")
    if price_str == "None":
        print "Warning: AWS response: SpotPrice field not available: " + str(resp)
        return ()
    try:
        return (float(price_str),)
    except ValueError:
        print "Warning: AWS response: Price string is invalid: " + str(resp)
        return ()

parser = argparse.ArgumentParser(description='Check ec2 spot prices. Written by joshblake@gmail.com.')
parser.add_argument('-s','--sms', action='store_true',help='Alert via SMS if price exceeds the threshold')
parser.add_argument('-t','--threshold',default=2.8,type=float,help='Set the SMS alert threshold price (default $2.80)')
parser.add_argument('-l','--loop',action='store_true',help='Loop until CTRL-C is pressed')
parser.add_argument('-d','--delay',default=300.0,type=float,help='Set the delay in seconds for each loop (default 300, minimum 60)')
args = parser.parse_args()

#60 is arbitrary minimum, but prices are unlikely to change more often,
#and do you really want to spam texts to your phone more than once a minute?
#Also, both AWS and Twilio have rate limits (usually much lower than 1/minute though.)
loop_delay = max(60.0,args.delay) #seconds

print "Alert to SMS: {}".format(args.sms)

if args.sms:
    (twilio_account,twilio_auto_token,from_number,to_number) = load_twilio_credentials()
    tw_client = TwilioRestClient(twilio_account, twilio_auto_token)
    print "To cell number: {}".format(to_number)

print "SMS Alert Threshold: {}".format(args.threshold)
print "Loop: {}".format(args.loop)
print "Loop Delay: {}".format(loop_delay)
print

ec2_client = boto3.client('ec2')

try:
    while True:
        price_tup = check_price(ec2_client, \
                                instanceType, \
                                availabilityZone, \
                                productDescription)
        if len(price_tup) == 0:
            print "Price not available"
            continue
        else:
            price = price_tup[0]
        timestr = datetime.datetime.now().strftime("%Y-%m-%d %I:%M:%S %p")
        if args.sms and price > args.threshold:
            #alert to sms
            msg = "Alert! {} price: ${} > ${} @ {}" \
                .format(instanceType, price, args.threshold, timestr)
            print "{} Sending txt alert: '{}'".format(timestr, msg)
            tw_client.messages.create(to=to_number, from_=from_number, body=msg)
        elif price > args.threshold:
            print "{} Alert! {} price: ${} > ${}".format(timestr, instanceType, price, args.threshold)
        else:
            print "{} {} price: ${}".format(timestr, instanceType, price)
        if not args.loop:
            break
        time.sleep(loop_delay)
except KeyboardInterrupt:
    pass
