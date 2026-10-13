#!/usr/bin/env python3

import sys
import signal
import logging
import urllib.parse
import csv
import os
import json
import xml.etree.ElementTree as ET
import argparse
import requests
import time
from datetime import datetime, timezone

SN_DATETIME_FORMAT = "%Y-%m-%d %H:%M:%S"
SN_ENCODING = "windows-1252" # Encoding of ServiceNow CSV exports
XML_ENCODING = "utf-8" # ServiceNow XML exports declare themselves as UTF-8
DEFAULT_EXPORT_DIR = "./export/"
STATE_FILE_NAME = "{0}.state.json"

# Supported export types.
# url_flag: the URL parameter that tells ServiceNow which format to export as, e.g. incident_list.do?XML
# accept: the Accept header to send
# ext: the file extension to use for page files and the combined file
EXPORT_TYPES = {
    "csv": {"url_flag": "CSV", "accept": "text/csv", "ext": ".csv"},
    "xml": {"url_flag": "XML", "accept": "application/xml, text/xml", "ext": ".xml"},
}

log = logging.getLogger()

class State:
    def __init__(self):
        self.delta_timestamp = ""
        self.last_sysid = ""
        self.page_num = 0
state = State()

def getStateFileName() -> str:
    return os.path.join(config.export_dir, STATE_FILE_NAME.format(config.out_file))

def saveState(state):
    if (config.no_state):
        return # Skip if state file not being used
    
    stateFilePath = getStateFileName()
    stateOut = {}
    stateOut["last_sysid"] = state.last_sysid
    stateOut["page_num"] = state.page_num
    stateOut["delta_timestamp"] = state.delta_timestamp

    stateJson = json.dumps(stateOut)
    log.debug("Saving state: \n{0}".format(stateJson))

    with open(stateFilePath, "w") as f:
        json.dump(stateOut, f)

def loadState(state:State):
    log.debug("Loading state")

    with open(getStateFileName(), "r") as f:
        stateIn = json.load(f)

    if ("page_num" in stateIn): state.page_num = int(stateIn["page_num"])
    if ("delta_timestamp" in stateIn): state.delta_timestamp = stateIn["delta_timestamp"]
    if ("last_sysid" in stateIn): state.last_sysid = stateIn["last_sysid"]


class Config:
    def __init__(self):
        self.auth_type = ""
        self.auth_username = ""
        self.auth_password = ""
        self.auth_cookies = ""
        #self.auth_browser_type = ""
        self.instance_url = ""
        self.export_type = "csv"
        self.page_size = 1000
        self.resume = False
        self.start_sysid = ""
        self.start_page = 0
        self.export_table = ""
        self.export_query = ""
        self.export_dir = os.path.join(".", DEFAULT_EXPORT_DIR)
        self.export_fields = "*"
        self.out_file = "export"
        self.display_values = True
        self.min_rows = 0
        self.delta_export = False
        self.delta_timestamp = ""
        self.delta_timestamp_file = ""
        self.delta_field = "sys_updated_on"
        self.output_timestamp = False
        self.work_dir = "./"
        self.combine_output = False
        self.no_state = False
        self.progress = False
        self.proxy = ""


config = Config()

def debugConfig():
    log.debug("{0}={1}".format("auth_type", config.auth_type))
    log.debug("{0}={1}".format("auth_username", config.auth_username))
    log.debug("{0}={1}".format("auth_cookies", config.auth_cookies))
    #log.debug("{0}={1}".format("auth_browser_type", config.auth_browser_type))
    log.debug("{0}={1}".format("instance_url", config.instance_url))
    log.debug("{0}={1}".format("export_type", config.export_type))
    log.debug("{0}={1}".format("page_size", config.page_size))
    log.debug("{0}={1}".format("resume", config.resume))
    log.debug("{0}={1}".format("start_sysid", config.start_sysid))
    log.debug("{0}={1}".format("start_sysid", config.start_page))
    log.debug("{0}={1}".format("export_table", config.export_table))
    log.debug("{0}={1}".format("temp_dir", config.export_dir))
    log.debug("{0}={1}".format("export_fields", config.export_fields))
    log.debug("{0}={1}".format("out_file", config.out_file))
    log.debug("{0}={1}".format("display_values", config.display_values))
    log.debug("{0}={1}".format("min_rows", config.min_rows))
    log.debug("{0}={1}".format("delta_export", config.delta_export))
    log.debug("{0}={1}".format("delta_timestamp", config.delta_timestamp))
    log.debug("{0}={1}".format("delta_field", config.delta_field))
    log.debug("{0}={1}".format("work_dir", config.work_dir))
    log.debug("{0}={1}".format("no_state", config.no_state))
    log.debug("{0}={1}".format("combine_output", config.combine_output))
    log.debug("{0}={1}".format("progress", config.progress))
    log.debug("{0}={1}".format("proxy", config.proxy))



def loadConfigFile(fname: str, config: Config):
    """
    Load a configuration from file.
    """

    log.info("Loading config file {0}".format(fname))

    with open(fname, "r") as f:
        fData = json.load(f)

        if ("auth_type" in fData): config.auth_type = fData["auth_type"]
        if ("auth_username" in fData): config.auth_username = fData["auth_username"]
        if ("auth_password" in fData): config.auth_password = fData["auth_password"]
        if ("auth_cookies" in fData): config.auth_cookies = fData["auth_cookies"]
        #if ("auth_browser_type" in fData): config.auth_browser_type = fData["auth_browser_type"]
        if ("instance_url" in fData): config.instance_url = fData["instance_url"]
        if ("export_type" in fData): config.export_type = fData["export_type"]
        if ("page_size" in fData): config.page_size = int(fData["page_size"])
        if ("resume" in fData): config.resume = fData["resume"]
        if ("start_sysid" in fData): config.start_sysid = fData["start_sysid"]
        if ("start_page" in fData): config.start_page = fData["start_page"]
        if ("export_table" in fData): config.export_table = fData["export_table"]
        if ("export_query" in fData): config.export_query = fData["export_query"]
        if ("export_fields" in fData): config.export_fields = fData["export_fields"]
        if ("out_file" in fData): config.out_file = fData["out_file"]
        if ("display_values" in fData): config.display_values = bool(fData["display_values"])
        if ("min_rows" in fData): config.min_rows = bool(fData["min_rows"])
        if ("delta_export" in fData): config.delta_export = fData["delta_export"]
        if ("delta_timestamp" in fData): config.delta_timestamp = fData["delta_timestamp"]
        if ("delta_field" in fData): config.delta_field = fData["delta_field"]
        if ("progress" in fData): config.progress = bool(fData["progress"])
        if ("proxy" in fData): config.proxy = fData["proxy"]
        

class ExportResult:
    def __init__(self):
        self.pages = []

def getUrl(root:str, path:str, parms={}) -> str:
    """
    Build a URL from a root, the path, and URL query parameters (optional).
    """

    url = "{0}".format(root)
    if (not url.startswith("http://") and not url.startswith("https://")):
        url = "https://{0}".format(url)

    urlParms = ""
    if len(parms) > 0:
        urlParms = "?"+urllib.parse.urlencode(parms)
    url = "{0}/{1}{2}".format(url, path, urlParms)

    return url


def tryLoginDo(session: requests.Session):
    """
    Try to login using basic auth credentials using login.do.
    """
    #Post to login.do

    # Success: a 302 redirect
    # Fail: a 200 refresh of the login page

    log.debug("Attempting login.do")

    url = getUrl(config.instance_url, "login.do")
    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept":"*/*"
    }
    body = {
        "sys_action":"sysverb_login",
        "user_name":config.auth_username,
        "user_password":config.auth_password
    }

    response = session.post(url, headers=headers, data=body, allow_redirects=False)

    sessionCookie = session.cookies.get("JSESSIONID")
    if (response.status_code == 302):
        if (sessionCookie):
            log.debug("Session opened: {0}".format(sessionCookie))
        else:
            raise Exception("Login successful, but didn't get a session cookie")

        # Success
        return
    
    else:
        # Likely a fail
        raise Exception("Login attempt failed {0} {1}".format(response.status_code))

def requestExport(session: requests.Session, page_num=0, last_sysid=None, fname: str = ""):
    """
    Fetch an export of data from ServiceNow in the configured export type (CSV or XML).
    """

    exportType = EXPORT_TYPES[config.export_type]

    query = config.export_query
    # Detect and throw exception if there's complexities in query that may cause issues 
    # with this script auto-inserting the sys_id query
    # ^NQ for multiple queries in 1
    # ^ORDERBY for setting the order
    queryHasNQ = query.find("^NQ") > -1
    queryHasOrderBy = query.find("^ORDERBY") > -1
    if (queryHasNQ): raise Exception(f"Query cannot contain '^NQ': {query}")
    if (queryHasOrderBy): raise Exception(f"Query cannot contain '^ORDERBY': {query}")

    queryParts = []

    if (last_sysid):
        queryParts.append(f"sys_id>{last_sysid}")

    if (config.delta_export):
        queryParts.append(f"{config.delta_field}>{state.delta_timestamp}")

    queryParts.append(config.export_query)
    query = "^".join(queryParts)

    log.info(f"Exporting data, page: {page_num}, table: {config.export_table}, type: {config.export_type}, rows: {config.page_size}, query: {query}")

    urlParms = {
        exportType["url_flag"]:"",
        "sysparm_query":query,
        "sysparm_orderby":"sys_id", # always order by sys_id, we use this for fetching in chunks
        "sysparm_record_count":config.page_size,
        "sysparm_display_value": config.display_values
    }
    if config.export_fields == "*":
        urlParms["sysparm_default_export_fields"] = "all"
    else:
        # Always include sys_id
        fieldList = config.export_fields.split(",")
        if not "sys_id" in fieldList: 
            log.debug("Adding sys_id to field list")
            fieldList.append("sys_id")
        urlParms["sysparm_fields"] = ",".join(fieldList)

    url = getUrl(config.instance_url, "{0}_list.do".format(config.export_table), urlParms)
    
    headers = {
        "Accept": exportType["accept"]
    }

    #response = session.get(url, headers=headers)
    response = session.get(url, headers=headers, stream=True)

    animation_frames = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
    frame_idx = 0
    bytesTotal = int(response.headers.get("content-length", 0))
    if (bytesTotal > 0): bytesTotalStr = printBytesNum(bytesTotal)
    else :bytesTotalStr = "???"
    bytesDownloaded = 0
    chunkSize = 8192 # TODO should this be config somewhere?
    progLength = 40 # terminal chars that progress anmation it will take up
    with open(fname, "wb") as f:
        for chunk in response.iter_content(chunk_size = chunkSize):
            if chunk:
                f.write(chunk)

                if (config.progress):
                    bytesDownloaded += len(chunk)
                    # Cycle through the animation frames
                    spinner = animation_frames[frame_idx % len(animation_frames)]
                    frame_idx += 1
                    if (frame_idx > len(animation_frames)): frame_idx = 0
                    progressOut = f"\r{spinner}  {printBytesNum(bytesDownloaded)} / {bytesTotalStr}"

                    sys.stdout.write(progressOut)
                    sys.stdout.flush()

    # Request complete, animation complete
    # Add newline before other lines begin
    if (config.progress):
        sys.stdout.write("\n")
        sys.stdout.flush()
    
    response.raise_for_status()

    return

def printBytesNum(a:int, scale: str="auto"):

    if scale == "auto":
        if (a <= 1024): scale = "b"
        elif (a <= 1048576): scale = "kb"
        elif (a <= 1073741824): scale = "mb"

    if scale == "b":
        return f"{a:,} B"
    if scale == "kb":
        return f"{a/1024:,.2f} KB"
    if scale == "mb":
        return f"{a/1024/1024:,.2f} MB"

def csvPageHasRows(fname: str) -> bool:
    """
    Quickly check whether a CSV page contains any rows of data (not just the header row).
    """

    # Check how many rows there are.
    # If it's just the header row and nothing else, there's no data.
    # There should be at least 2: 1 after the header and 1 after at least 1 row. If there's only 1 newline, it's the header and nothiner else.
    # Sadly, can't use python's CSV module for this, it's got issues reading from strings instead of files.
    newLineCount = 0
    chunk_size = 8192
    with open(fname, "r", encoding=SN_ENCODING) as f:
        while chunk := f.read(chunk_size):
            newLineCount += chunk.count("\n")
            if (newLineCount > 2):
                break

    return newLineCount >= 2

def readCsvPage(fname: str, lastSysId: str):
    """
    Read a page of CSV data. Returns a tuple of (row count, last sys_id).
    If the page has no rows, the given lastSysId is returned unchanged.
    """

    if (not csvPageHasRows(fname)):
        log.debug("CSV has no rows of data")
        return (0, lastSysId)

    # Read the CSV
    # Try to read to get the last sys_id

    # This is really stupid, but Python CSV works better with files than strings.
    # Otherwise, I was getting issues where the row would only have the 1st cell, not the whole row.
    # Getting the next row would return 2 empty cells, then the next 1 cell.
    # I suspect it's having issues with every cell in quotation.
    # This feels dumb, needing to save it out of memory, only to read it from the file again, but it works.
    rowCount = 0
    with open(fname, "r", newline="", encoding=SN_ENCODING) as f:
        csvReader = csv.reader(f, csv.unix_dialect)

        # Read the 1st row, should be the column headers. Look for "sys_id".
        csvRow1 = next(csvReader)
        log.debug("CSV headers: {0}".format(", ".join(csvRow1)))

        sysIdColNum = -1
        try:
            sysIdColNum = csvRow1.index("sys_id")
        except ValueError as ex:
            raise ValueError("CSV header doesn't contain column for sys_id")

        for line in csvReader:
            lastSysId = line[sysIdColNum]
            rowCount = rowCount + 1

    log.debug("Last sys_id: {0}".format(lastSysId))
    log.debug("{0} rows of data in CSV".format(rowCount))
    return (rowCount, lastSysId)

def iterXmlRecords(fname: str):
    """
    Stream the record elements out of a ServiceNow XML export, one at a time, without loading the whole file into memory.

    A ServiceNow XML export looks like:
        <xml>
            <incident>
                <number>INC0010001</number>
                <sys_id>...</sys_id>
                ...
            </incident>
            <incident>...</incident>
        </xml>
    Each direct child of the root element is one record. The elements within it are the fields.
    """

    depth = 0
    root = None
    with open(fname, "rb") as f:
        for event, elem in ET.iterparse(f, events=("start", "end")):
            if event == "start":
                depth += 1
                if depth == 1:
                    root = elem
            else:
                depth -= 1
                if depth == 1:
                    # A record element just ended. Hand it over, then free it from memory.
                    yield elem
                    elem.clear()
                    if root is not None:
                        root.remove(elem)

def readXmlPage(fname: str, lastSysId: str):
    """
    Read a page of XML data. Returns a tuple of (row count, last sys_id).
    If the page has no rows, the given lastSysId is returned unchanged.
    """

    rowCount = 0
    try:
        for record in iterXmlRecords(fname):
            sysIdElem = record.find("sys_id")
            if (sysIdElem is None or not sysIdElem.text):
                raise ValueError("XML record <{0}> doesn't contain an element for sys_id".format(record.tag))

            lastSysId = sysIdElem.text.strip()
            rowCount = rowCount + 1
    except ET.ParseError as ex:
        raise ValueError("Export is not valid XML, the instance may have returned an error or login page instead. File: {0}. Error: {1}".format(fname, ex))

    if (rowCount == 0):
        log.debug("XML has no rows of data")
    else:
        log.debug("Last sys_id: {0}".format(lastSysId))
        log.debug("{0} rows of data in XML".format(rowCount))

    return (rowCount, lastSysId)

def readPage(fname: str, lastSysId: str):
    """
    Read a page of exported data in the configured export type. Returns a tuple of (row count, last sys_id).
    """

    if config.export_type == "csv":
        return readCsvPage(fname, lastSysId)
    if config.export_type == "xml":
        return readXmlPage(fname, lastSysId)
    raise ValueError("Unsupported export type: {0}".format(config.export_type))

def exportPages(session: requests.Session) -> ExportResult:
    """
    Export and save data from ServiceNow, a page at a time, in the configured export type.
    """

    # Get the export
    lastSysId = state.last_sysid
    totalRowCount = 0
    fileExt = EXPORT_TYPES[config.export_type]["ext"]

    exportResult = ExportResult()

    while True:
        log.debug(f"Fetching page {state.page_num}")
        fname = os.path.join(config.export_dir, "{1}.page_{0}{2}".format(state.page_num, config.out_file, fileExt))
        log.debug("Writing to {0}".format(fname))
        requestExport(session, state.page_num, last_sysid=lastSysId, fname=fname)

        # Read the page to count the rows and find the last sys_id
        (rowCount, lastSysId) = readPage(fname, lastSysId)

        if (rowCount == 0):
            if (config.min_rows > 0):
                _offsetPlus1Page = (state.page_num+1) * config.page_size
                log.debug("Attempted export of {0} / min_rows {1}".format(_offsetPlus1Page, config.min_rows))

                if (config.min_rows > 0 and _offsetPlus1Page < config.min_rows):
                    log.debug("Continuing export")
                else:
                    log.debug("Reached end of export")
                    log.debug("Deleting last export, should be empty with no rows")
                    os.remove(fname)
                    return exportResult

            else:
                log.debug("Reached end of export")
                log.debug("Deleting last export, should be empty with no rows")
                os.remove(fname)
                return exportResult

        exportResult.pages.append(fname)
        state.last_sysid = lastSysId
        totalRowCount = totalRowCount + rowCount

        # End of page
        state.page_num = state.page_num + 1

        # Save the state
        saveState(state)

def combineCsvFiles(outFileName:str, files:list):
    """
    Combine multiple CSV files into one CSV file.
    """

    log.debug("Combining output to file: {0}".format(outFileName))
    if (len(files) < 1): 
        log.info("No files to combine")
        #raise Exception("No files to combine")

    with open(outFileName, "w", encoding=SN_ENCODING) as outFile:
        is1stFile=True
        for inFileName in files:
            log.debug("Combining file {0}".format(inFileName))
            with open(inFileName, "r", encoding=SN_ENCODING) as inFile:
                if is1stFile:
                    # This is the 1st file.
                    # Copy everything, including the header
                    is1stFile = False
                else:
                    # Not the 1st file
                    # Skip the header
                    inFile.readline() # Read past the 1st line
                
                for data in inFile.read():
                    outFile.write(data)

    log.debug("Finished writing to {0}".format(outFileName))

def combineXmlFiles(outFileName:str, files:list):
    """
    Combine multiple XML files into one XML file.
    Each page is a complete XML document with its own root element, so the records are streamed
    out of each page and written under a single new root element.
    """

    log.debug("Combining output to file: {0}".format(outFileName))
    if (len(files) < 1):
        log.info("No files to combine")

    with open(outFileName, "w", encoding=XML_ENCODING) as outFile:
        outFile.write('<?xml version="1.0" encoding="UTF-8"?>\n')
        outFile.write("<xml>\n")
        for inFileName in files:
            log.debug("Combining file {0}".format(inFileName))
            for record in iterXmlRecords(inFileName):
                record.tail = None # Don't carry over whitespace from the source file
                outFile.write(ET.tostring(record, encoding="unicode"))
                outFile.write("\n")
        outFile.write("</xml>\n")

    log.debug("Finished writing to {0}".format(outFileName))

def combineFiles(outFileName:str, files:list):
    """
    Combine multiple page files into one file, in the configured export type.
    """

    if config.export_type == "csv":
        return combineCsvFiles(outFileName, files)
    if config.export_type == "xml":
        return combineXmlFiles(outFileName, files)
    raise ValueError("Unsupported export type: {0}".format(config.export_type))

def validateTimestamp(timestamp):
    """
    Validate that the delta timestamp is in the correct SN format.
    """

    #Just try to read the timestamp. It'll either work, or throw a ValueError.
    log.debug("Validating delta timestamp: {0}".format(config.delta_timestamp))
    datetime.strptime(timestamp, SN_DATETIME_FORMAT)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--auth-type", "-a", choices=["none", "basic", "cookies"], help="Type of authentication to use.")
    parser.add_argument("--auth-username", "-au", help="Username to authenticate with.")
    parser.add_argument("--auth-password", "-ap", help="Password to authenticate with.")
    #parser.add_argument("--auth-browser-type", "-ab", choices=["chrome", "firefox"], help="Type of browser to load cookies from.")
    parser.add_argument("--auth-cookies", "-ac", help="When using cookies auth, a semi-colon separated list of cookies to use.")
    parser.add_argument("--instance-url", "-i", help="Base URL of the SN instance. E.g. myinstance.service-now.com")
    parser.add_argument("--verbose", "-v", action="store_true", default=False, help="Enable verbose logging.")
    parser.add_argument("--config", "-c", help="Load config from config file.")
    parser.add_argument("--combine-output", "-C", action="store_true", help="Combine the pages of results into 1 output file. Not recommended for multi-GB size exports.")
    parser.add_argument("--export-type", "-e", choices=list(EXPORT_TYPES.keys()), help="Type of export. Default: csv")
    parser.add_argument("--export-table", "-t", help="Name of the table to export data from.")
    parser.add_argument("--export-fields", "-f", help="List of fields to export, comma-separated, or '*' for all fields.")
    parser.add_argument("--export-query", "-q", help="Query to use when exporting data.")
    parser.add_argument("--page-size", "-s", type=int, help="How many rows to export per page.")
    parser.add_argument("--resume", "-r", action="store_true", help="Resume an incomplete export.")
    parser.add_argument("--start-sysid", type=str, help="The sys_id to start exporting from (not including the sys_id). Useful for resuming a failed export. Overrides the last sysid in the state file.")
    parser.add_argument("--start-page", type=int, help="The page to start exporting from. Useful for resuming a failed export. Overrides the last page in the state file.")
    parser.add_argument("--export-dir", "-T", help="Directory to save export files to.")
    parser.add_argument("--out", "-o", help="Name of file to output the export to. Pages of results will also use this name.")
    parser.add_argument("--display-values", "-d", help="Enable display values when exporting data.")
    parser.add_argument("--no-display-values", "-D", help="Disable display values when exporting data.")
    parser.add_argument("--min-rows", "-m", type=int, help="The minimum amount of rows to export. Useful when there's lots of data 'hidden for security reasons' and may result in an empty page of data. If not provided, export will end on the 1st empty page of data.")
    parser.add_argument("--no-state", "-S", help="Don't save the state. Disables resume support.")
    parser.add_argument("--delta-export", "-X", action="store_true", help="Enable delta exports, only exporting data sys_updated_on since the last export.")
    parser.add_argument("--delta-timestamp", "-x", help="Add a sys_updated_on query to only export data updated after the given timestamp. Must be correctly formatted UTC timestamp YYYY-MM-DD HH:MM:SS. Leave blank if you want to use what's in the state file.")
    parser.add_argument("--delta-field", "-F", help="The field to filter the delta timestamp on. Default: sys_updated_on")
    parser.add_argument("--progress", "-P", action="store_true", help="Show progress while exporting.")
    parser.add_argument("--proxy", help="Web proxy address to use, authentication must be in-line. http://<ip>:<port> or http://<username>:<password>@<ip>:<port>")
    args = parser.parse_args()

    logging.basicConfig(filename=None, level=args.verbose and logging.DEBUG or logging.INFO)

    if (args.config):
        loadConfigFile(args.config, config)

    if (args.auth_type): config.auth_type = args.auth_type
    if (args.auth_username): config.auth_username = args.auth_username
    if (args.auth_password): config.auth_password = args.auth_password 
    if (args.auth_cookies): config.auth_cookies = args.auth_cookies
    #if (args.auth_browser_type): config.auth_browser_type = args.auth_browser_type
    if (args.instance_url): config.instance_url = args.instance_url 
    if (args.export_type): config.export_type = args.export_type 
    if (args.page_size): config.page_size = args.page_size 
    if (args.resume): config.resume = True
    if (args.start_sysid): config.start_sysid = args.start_sysid 
    if (args.start_page): config.start_page = args.start_page 
    if (args.export_table): config.export_table = args.export_table 
    if (args.export_query): config.export_query = args.export_query
    if (args.export_dir): config.export_dir = args.export_dir
    if (args.export_fields): config.export_fields = args.export_fields
    if (args.out): config.out_file = args.out
    if (args.display_values): config.display_values = True
    if (args.no_display_values): config.display_values = False
    if (args.min_rows): config.min_rows = args.min_rows
    if (args.delta_export): config.delta_export = args.delta_export
    if (args.delta_timestamp): config.delta_timestamp = args.delta_timestamp
    if (args.delta_field): config.delta_field = args.delta_field
    if (args.combine_output): config.combine_output = args.combine_output
    if (args.no_state): config.no_state = args.no_state
    if (args.progress): config.progress = args.progress
    if (args.proxy): config.proxy = args.proxy
    

    debugConfig()

    # Check the config
    if (not config.instance_url): raise ValueError("instance_url cannot be empty")
    if (not config.export_table): raise ValueError("export_table cannot be empty")
    if (not config.export_type in EXPORT_TYPES): raise ValueError("export_type must be one of: {0}".format(", ".join(EXPORT_TYPES.keys())))
    if (config.page_size < 1): raise ValueError("page_size cannot be less than 1")
    if (not config.export_fields): raise ValueError("export_fields cannot be empty")
    if (not config.out_file): raise ValueError("out_file cannot be empty")
    if (config.min_rows < 0): raise ValueError("min_rows must be a number above zero, or zero to end on the 1st empty page")
    if (config.output_timestamp and not config.delta_timestamp_file): raise ValueError("delta_timestamp_file must be provided when using output_timestamp")

    try:
        startTime = time.time()

        # Create export dir if missing. Must happen before the state file is saved into it.
        if not os.path.exists(config.export_dir):
            os.makedirs(config.export_dir, exist_ok=True)

        # Load state
        if (not config.no_state):
            if (os.path.exists(getStateFileName())):
                loadState(state)
            else:
                log.info("State file doesn't exist, creating")
                saveState(state)
        else:
            log.info("Not using state file, resume & delta exports not supported.")
            config.resume = False

        if (config.delta_timestamp):
            log.info(f"Delta timestamp override: {config.delta_timestamp}")
            state.delta_timestamp = config.delta_timestamp

        if (config.resume and config.start_sysid):
            log.info(f"Start sysid override: {config.start_sysid}")
            state.last_sysid = config.start_sysid

        if (config.resume and config.start_page):
            log.info(f"Start page override: {config.start_page}")
            state.page_num = config.start_page

        if (state.delta_timestamp): 
            try:
                validateTimestamp(state.delta_timestamp)
            except Exception:
                raise Exception("delta_timestamp is not a ServiceNow formatted timestamp. E.g. 2021-08-15 18:21:06")

        session = requests.Session()
        log.debug("Auth type: {0}".format(config.auth_type))
        if config.auth_type == "none":
            log.debug("Not trying to authenticate")

        if config.auth_type == "basic":
            # Try to log in to start a session
            if (not config.auth_username): raise ValueError("auth_username cannot be empty in basic auth")
            if (not config.auth_password): raise ValueError("auth_password cannot be empty in basic auth")
            tryLoginDo(session)

        if config.auth_type == "cookies":
            # Just add the session token to the session cookies
            
            if (not config.auth_cookies): raise ValueError("auth_cookies cannot be empty in session auth")

            # WARNING: will encounter issues if cookie contains = or ;. 
            # However, this is a known issue, and it's frowned upon for cookies to have these values anyway.
            log.debug("Adding session token to cookies")
            for cookie in config.auth_cookies.split(";"):
                eqIndex = cookie.find("=") # Find the first = sign
                if eqIndex == -1:
                    # Equals not found. What?
                    log.warning("Cookie pair doesn't contain equals. Skipping line. Cookie: {0}".format(cookie))

                cookieName = cookie[:eqIndex] # Before the equals
                cookieVal = cookie[eqIndex+1:] # After the equals
                session.cookies.set(name=cookieName, value=cookieVal, domain=config.instance_url)

        # Setup the proxy
        if (config.proxy):
            log.debug(f"Adding proxy: {config.proxy}")
            session.proxies = {
                "http": config.proxy,
                "https": config.proxy
            }
        
        # Do the export
        if (config.resume and (state.last_sysid or state.page_num != 0)):
            log.info(f"Resuming export from sys_id {state.last_sysid}, page {state.page_num}")

        if (not config.resume):
            log.debug("Resume disabled, clearing resume state")
            state.page_num = 0
            state.last_sysid = ""

        result = exportPages(session)

        if (config.combine_output):
            combinedFileName = config.out_file
            fileExt = EXPORT_TYPES[config.export_type]["ext"]
            if not combinedFileName.lower().endswith(fileExt):
                combinedFileName = f"{combinedFileName}{fileExt}"
            combineFiles(combinedFileName, result.pages)

        # Reset the state
        state.last_sysid = "" # Reset last sysid
        state.page_num = 0
        state.delta_timestamp = datetime.now().strftime(SN_DATETIME_FORMAT)
        saveState(state)

    except Exception as ex:
        if (log.level == logging.DEBUG):
            log.error(ex)
        else:
            log.error(ex, exc_info=False)
        raise ex
    
    finally:
        stopTime = time.time()
        log.info("Completed in {0}s".format(int(stopTime-startTime)))

def signal_handler(sig, frame):
    log.info("SIGINT, exiting...")
    sys.exit(0)
signal.signal(signal.SIGINT, signal_handler)

if __name__ == "__main__":
    main()