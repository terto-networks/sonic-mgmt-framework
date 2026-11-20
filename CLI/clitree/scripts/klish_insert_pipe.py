#!/usr/bin/python
###########################################################################
#
# Copyright 2019 Dell, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
###########################################################################


''' This script extends every show and get COMMAND with pipe option
    ----------------------------------------------------------------'''

import sys
import os
import re
import traceback
from lxml import etree
import xml.etree.ElementTree as ET

DBG_FLAG                = False
PIPE_XML                = "include/pipe.xml"
PIPE_WITHOUT_DISPLAY_XML = "include/pipe_without_display_xml.xml"
DEFAULT_NS_HREF         = "http://www.dellemc.com/sonic/XMLSchema"
XSI_NS_HREF             = "http://www.dellemc.com/sonic/XMLSchema-instance"
XI_NS_HREF              = "http://www.w3.org/2001/XInclude"
COMMAND_XPATH_EXPR      = ".//{"+DEFAULT_NS_HREF+"}VIEW/{"+DEFAULT_NS_HREF+"}COMMAND"
HIDDEN_CMD_XPATH_EXPR   = ".//{"+DEFAULT_NS_HREF+"}VIEW[@name='hidden-view']/{"+DEFAULT_NS_HREF+"}COMMAND"
ACTION_XPATH_EXPR       = "{"+DEFAULT_NS_HREF+"}ACTION"

#
# *** NOTE : List of action plugins for which display-xml need not be appended ***
#
actionlst               = ['clish_history', 'clish_file_print', 'clish_show_alias_plugin', \
                            'clish_logger_on_off', 'clish_show_batch_plugin']


'''
@brief Align and Save tempfile to outputfile
@param[in] Temporary file name
@param[in] Output file name
'''
def align_and_save(temp_file_name, output_file_name):
    try:
        parser = etree.XMLParser(remove_blank_text=True, resolve_entities=False)
        root = etree.parse(temp_file_name, parser)
        root.write(output_file_name, pretty_print=True, xml_declaration=True, encoding=root.docinfo.encoding)
    except:
        error = parser.error_log[0]
        print("Error parsing ", os.path.basename(outputfile.name), error.message)
        print("Error writing ", out_file_name, sys.exc_info()[0])
        sys.exit(102)


'''
@brief Test whether pipe can be added to given command and insert it
@param[in] COMMAND tag found in xml
@return COMMAND tag with/without pipe sub-element added
'''
def addpipe(command):
   splitstr = command.get('name').split()
   action_el = command.find(ACTION_XPATH_EXPR)
   action = action_el.get('builtin') if action_el is not None else None
   if (splitstr[0] == 'show' or splitstr[0] == 'get'):
      if action in actionlst:
          etree.SubElement(command, "{"+XI_NS_HREF+"}include", href = PIPE_WITHOUT_DISPLAY_XML)
      else:
          etree.SubElement(command, "{"+XI_NS_HREF+"}include", href = PIPE_XML)
          wrap_action(action_el)

      if DBG_FLAG == True:
          print("Adding Pipe for cmd: ", splitstr)
   return command


# TertoOS (20/11/2026): no upstream quem aplicava o `| grep` era o renderer Python
# (rpipe_utils, so' p/ comandos REST/Jinja). As ACTIONs TertoOS sao shell e IGNORAVAM o
# pipe (o filtro era aceito e a saida vinha inteira). Aqui a ACTION shell de todo `show`
# vira uma funcao; com filtro, a saida passa pelo scripts/tos_pipe.py.
# O regex vai em ASPAS SIMPLES sem escape (${^n_LINE}): chega exato, e o ptype
# TERTOOS_PIPE_REGEX proibe a aspa simples (nao da' p/ sair das aspas).
PIPE_STAGES      = 3
TOS_PIPE_SCRIPT  = "/usr/sbin/cli/scripts/tos_pipe.py"
WRAP_MARK        = "__tos_show"


def wrap_text(text):
   """Texto shell original -> texto embrulhado (sem filtro, executa igual ao original)."""
   args = " ".join("'${^%d_switch_var}' '${^%d_LINE}' '${^%d_ignore-case}'" % (n, n, n)
                   for n in range(1, PIPE_STAGES + 1))
   return ("\n" + WRAP_MARK + "() {\n" + text.strip("\n") + "\n}\n"
           "if [ -n '${^1_switch_var}' ]; then\n"
           "  " + WRAP_MARK + " 2>&1 | python3 " + TOS_PIPE_SCRIPT + " " + args + "\n"
           "else\n"
           "  " + WRAP_MARK + "\n"
           "fi\n")


def wrap_action(action_el):
   """Embrulha so' ACTION shell (sem builtin, ou clish_script) com texto; idempotente."""
   if action_el is None:
      return
   if action_el.get('builtin') not in (None, 'clish_script'):
      return
   text = action_el.text or ""
   if not text.strip() or WRAP_MARK in text or len(action_el) != 0:
      return
   action_el.text = wrap_text(text)


'''
@brief Register Namespaces so that XPATH expression matches
'''
def registerns():
   ET.register_namespace("", DEFAULT_NS_HREF)
   ET.register_namespace("xsi", XSI_NS_HREF)
   ET.register_namespace("xi", XI_NS_HREF)


'''
@brief Convert the escaped characters back to their original form
@param[in] Input filename
@param[out] Temporary file
'''
def process_input_file(input_file_name, tempfile):
    try:
        if True:
                registerns()
                parser = etree.XMLParser(remove_blank_text=True, resolve_entities=False)
                tree = etree.parse(input_file_name,parser)
                root = tree.getroot()
                #root.set("xmlns:" + "xi", XI_NS_HREF)
                if DBG_FLAG == True:
                        print("Root Tag: ",root.tag)
                for command in root.findall(COMMAND_XPATH_EXPR):
                        if len(command) != 0:
                                command = addpipe(command)
                for command in root.findall(HIDDEN_CMD_XPATH_EXPR):
                        if len(command) != 0:
                                command = addpipe(command)

                tree.write(tempfile, xml_declaration=True, encoding=tree.docinfo.encoding, pretty_print=True)
    except IOError as e:
        traceback.print_exc(file=sys.stdout)
        print("Cannot open file: ", e.filename, ":", e.strerror)
        sys.exit(100)
    except:
        traceback.print_exc(file=sys.stdout)
        traceback.print_exc(limit=1, file=sys.stdout)
        print("process_input_file:Unknown error: ", sys.exc_info()[0])
        sys.exit(100)

def insert_pipe (dirpath, debug):

    DBG_FLAG = debug

    tmp_dirpath = dirpath + '/tmp'
    dirpath = dirpath + "/"
    tmp_dirpath = tmp_dirpath + "/"
    try:
        os.mkdir(tmp_dirpath)
    except OSError:
        print('The directory', tmp_dirpath, 'already exists. Using it.')
    except:
        error = parser.error_log[0]
        print("Unknown error", error.message)
        sys.exit (98)
    temp_file_name = tmp_dirpath + "out.xml"

    ''' The following loops go through each directory in the given
        input directory and reads each *.xml file in the directory
        for inserting the pipe '''
    for fname in os.listdir(dirpath):
        fname = dirpath + fname
        if not os.path.isfile (fname):
            if DBG_FLAG == True:
                print('Skipping', fname, 'since it is not a file')
            continue
        if DBG_FLAG == True:
            print('Parsing ', fname)
        if fname.endswith(".xml", re.I):
            try:
                temp_file = open(temp_file_name, "wb")
            except IOError as e:
                print(e.filename, ":", e.strerror)
                sys.exit(99)
            if DBG_FLAG == True:
                print(fname)
            process_input_file(fname, temp_file)
            temp_file.close()
            align_and_save(temp_file_name, fname)

    if os.path.exists(temp_file_name):
        os.remove(temp_file_name)
    if os.path.exists(tmp_dirpath):
        os.rmdir(tmp_dirpath)

'''
@brief Main Routine to insert pipe for every show and get COMMAND in all
        xml files, present in input-dir and save them in output-dir
'''
if __name__ == "__main__":

    if len(sys.argv) == 1 or sys.argv[1] == "--help":
        print("Usage:", sys.argv[0], "working-dir [--debug]")
        sys.exit(0)

    if len(sys.argv) == 3 and sys.argv[2] == "--debug":
        debug = True
    else:
        debug = False

    insert_pipe (sys.argv[1], debug)
    sys.exit(0)

