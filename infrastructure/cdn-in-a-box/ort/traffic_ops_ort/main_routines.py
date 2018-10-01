# Licensed to the Apache Software Foundation (ASF) under one
# or more contributor license agreements.  See the NOTICE file
# distributed with this work for additional information
# regarding copyright ownership.  The ASF licenses this file
# to you under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance
# with the License.  You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
# KIND, either express or implied.  See the License for the
# specific language governing permissions and limitations
# under the License.

"""
This module is meant to run the main routines of the script,
and performs a variety of operations based on the run mode.
"""

import os
import logging
import requests

#: A constant that holds the absolute path to the status file directory
STATUS_FILE_DIR = "/opt/ort/status"

class ORTException(Exception):
	"""Signifies an ORT related error"""
	pass

def syncDSState() -> bool:
	"""
	Queries Traffic Ops for the Delivery Service's sync state

	:raises ORTException: when something goes wrong
	:returns: whether or not an update is needed
	"""
	from . import to_api, configuration
	logging.info("starting syncDS state fetch")

	try:
		updateStatus = to_api.getUpdateStatus(configuration.HOSTNAME[0])[0]
	except (IndexError, ConnectionError, requests.exceptions.RequestException) as e:
		logging.critical("Server configuration not found in Traffic Ops!")
		logging.debug("%s", e, exc_info=True, stack_info=True)
		raise ORTException()
	except PermissionError as e:
		logging.critical("Failed to authenticate with the Traffic Ops server!")
		logging.debug("%s", e, exc_info=True, stack_info=True)
		raise ORTException()

	logging.info("Retrieved raw update status: %r", updateStatus)

	return 'upd_pending' in updateStatus and updateStatus['upd_pending']

def revalidateState() -> bool:
	"""pass"""
	return True

def deleteOldStatusFiles(myStatus:str):
	"""
	Attempts to delete any and all old status files

	:param myStatus: the current status - files by this name will not be deleted
	:raises ConnectionError: if there's an issue retrieving a list of statuses from
		Traffic Ops
	:raises OSError: if a file cannot be deleted for any reason
	"""
	from .configuration import MODE, Modes
	from . import to_api, utils

	doDeleteFiles = MODE is not Modes.REPORT

	for status in to_api.getStatuses():

		if doDeleteFiles and status != myStatus:
			fname = os.path.join("/opt/ORTstatus", status)
			logging.info("File '%s' to be deleted", fname)

			# check for user confirmation before deleting files in 'INTERACTIVE' mode
			if MODE != Modes.INTERACTIVE or utils.getYesNoResponse("Delete file %s?" % fname):
				logging.warning("Deleting file '%s'!", fname)
				os.remove(fname)

def setStatusFile() -> bool:
	"""
	Attempts to set the status file according to this server's reported status in Traffic Ops.

	.. warning:: This will create the directory '/opt/ORTstatus' if it does not exist, and may
		delete files there without warning!

	:returns: whether or not the status file could be set properly
	"""
	global STATUS_FILE_DIR
	from .configuration import MODE, Modes
	from . import to_api, utils
	logging.info("Setting status file")

	if not isinstance(MODE, Modes):
		logging.error("MODE is not set to a valid Mode (from traffic_ops_ort.configuration.Modes)!")
		return False

	try:
		myStatus = to_api.getMyStatus()
	except ConnectionError as e:
		logging.error("Failed to set status file - Traffic Ops connection failed")
		return False

	if not os.path.isdir(STATUS_FILE_DIR):
		logging.warning("status directory does not exist, creating...")
		doMakeDir = MODE is not Modes.REPORT

		# Check for user confirmation if in 'INTERACTIVE' mode
		if doMakeDir and (MODE is not Modes.INTERACTIVE or\
		   utils.getYesNoResponse("Create status directory '%s'?" % STATUS_FILE_DIR, default='Y')):
			try:
				os.makedirs(STATUS_FILE_DIR)
				return False
			except OSError as e:
				logging.error("Failed to create status directory '%s' - %s", STATUS_FILE_DIR, e)
				logging.debug("%s", e, exc_info=True, stack_info=True)
				return False
	else:
		try:
			deleteOldStatusFiles(myStatus)
		except ConnectionError as e:
			logging.error("Failed to delete old status files - Traffic Ops connection failed.")
			logging.debug("%s", e, exc_info=True, stack_info=True)
			return False
		except OSError as e:
			logging.error("Failed to delete old status files - %s", e)
			logging.debug("%s", e, exc_info=True, stack_info=True)
			return False

	fname = os.path.join(STATUS_FILE_DIR, myStatus)
	if not os.path.isfile(fname):
		logging.info("File '%s' to be created", fname)
		if MODE is not Modes.REPORT and\
		  (MODE is not Modes.INTERACTIVE or utils.getYesNoResponse("Create file '%s'?", 'y')):

			try:
				with open(fname, 'x'):
					pass
			except OSError as e:
				logging.error("Failed to create status file - %s", e)
				logging.debug("%s", e, exc_info=True, stack_info=True)
				return False

	return True

def processPackages() -> bool:
	"""
	Manages the packages that Traffic Ops reports are required for this server.

	:returns: whether or not the package processing was successfully completed
	"""
	from . import to_api

	try:
		myPackages = to_api.getMyPackages()
	except (ConnectionError, PermissionError) as e:
		logging.error("Failed to fetch package list from Traffic Ops - %s", e)
		logging.debug("%s", e, exc_info=True, stack_info=True)
		return False
	except ValueError as e:
		logging.error("Got malformed response from Traffic Ops! - %s", e)
		logging.debug("%s", e, exc_info=True, stack_info=True)
		return False

	for package in myPackages:
		# TODO - install these packages
		pass

	return True

def processServices() -> bool:
	"""
	Manages the running processes of the server, according to an ancient system known as 'chkconfig'

	:returns: whether or not the service processing was completed successfully
	"""
	from .to_api import getMyChkconfig

	chkconfig = getMyChkconfig()

	logging.debug("/ort/<hostname>/chkconfig response: %r", chkconfig)

	for item in chkconfig:
		logging.debug("Processing item %r", item)

		if not services.setServiceStatus(item):
			return False

	return True

def processConfigurationFiles() -> bool:
	"""
	Updates and backs up all of a server's configuration files.

	:returns: whether or not the configuration changes were successful
	"""
	from . import config_files, to_api, configuration

	try:
		config_files.initBackupDir()
	except OSError as e:
		logging.error("Couldn't create backup directory!")
		logging.warning("%s", e)
		logging.debug("", exc_info=True, stack_info=True)
		return False

	try:
		myFiles = to_api.getMyConfigFiles()
	except ConnectionError as e:
		logging.error("Failed to fetch configuration files - Traffic Ops connection failed! %s",e)
		logging.debug("%s", e, exc_info=True, stack_info=True)
		return False
	except ValueError as e:
		logging.error("Malformed configuration file response from Traffic Ops!")
		logging.debug("%s", e, exc_info=True, stack_info=True)
		return False

	for file in myFiles:
		try:
			file = config_files.ConfigFile(file)
			logging.info("\n============ Processing File: %s ============", file.fname)
			file.update()
			logging.info("\n============================================\n")

		# A bad object could just reflect an inconsistent reply structure from the API, so BADASSes
		# will attempt to continue. However, an issue updating a valid configuration is not
		# recoverable, even for BADASSes
		except config_files.ConfigurationError as e:
			logging.error("An error occurred while trying to update %s", file.name)
			logging.debug("%s", e, exc_info=True, stack_info=True)
			return False
		except ValueError as e:
			logging.error("%s does not appear to be a valid 'configfile' object!")
			logging.debug("%s", e, exc_info=True, stack_info=True)
			if configuration.MODE is not configuration.Modes.BADASS:
				return False
			logging.warning("Moving on because we're BADASS")

	return True

def run() -> int:
	"""
	This function is the entrypoint into the script's main flow from :func:`traffic_ops_ort.doMain`
	It runs the appropriate actions depending on the run mode

	:returns: an exit code for the script
	"""
	from . import configuration, to_api, utils, services

	# If this is just a revalidation, then we can exit if there's no revalidation pending
	if configuration.MODE == configuration.Modes.REVALIDATE:
		updateRequired = revalidateState()
		if not updateRequired:
			logging.info("No revalidation pending")
			return 0

		logging.info("in REVALIDATE mode; skipping package/service processing")

	# In all other cases, we check for an update to the Delivery Service and apply any found
	# changes
	else:
		updateRequired = syncDSState()

		# Bail on failures - unless this script is BADASS!
		if not setStatusFile():
			if configuration.MODE is not configuration.Modes.BADASS:
				logging.critical("Failed to set status as specified by Traffic Ops")
				return 2
			logging.warning("Failed to set status but we're BADASS, so moving on.")

		logging.info("\nProcessing Packages...")
		if not processPackages():
			logging.critical("Failed to process packages")
			if configuration.MODE is not configuration.Modes.BADASS:
				return 2
			logging.warning("Package processing failed but we're BADASS, so attempting to move on")
		logging.info("Done.\n")

		logging.info("\nProcessing Services...")
		if not processServices():
			logging.critical("Failed to process services.")
			if configuration.MODE is not configuration.Modes.BADASS:
				return 2
			logging.warning("Service processing failed but we're BADASS, so attempting to move on")
		logging.info("Done.\n")


	# All modes process configuration files
	logging.info("\nProcessing Configuration Files...")
	if not processConfigurationFiles():
		logging.critical("Failed to process configuration files.")
		return 2
	logging.info("Done.\n")

	if updateRequired:
		if configuration.MODE is not configuration.Modes.INTERACTIVE or\
		   utils.getYesNoResponse("Update Traffic Ops?", default='Y'):

			logging.info("\nUpdating Traffic Ops...")
			to_api.updateTrafficOps()
			logging.info("Done.\n")
		else:
			logging.warning("Traffic Ops was not notified of changes. You should do this manually.")

		return 0

	logging.info("Traffic Ops update not necessary")

	if services.NEEDED_RELOADS and not services.doReloads():
		logging.critical("Failed to reload all configuration changes")
		return 2

	return 0
