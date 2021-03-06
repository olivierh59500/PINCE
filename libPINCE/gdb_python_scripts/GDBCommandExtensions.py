# -*- coding: utf-8 -*-
"""
Copyright (C) 2016 Korcan Karaokçu <korcankaraokcu@gmail.com>

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see <http://www.gnu.org/licenses/>.
"""
import gdb
import pickle
import sys
import re
import struct
import io
from collections import OrderedDict

# This is some retarded hack
gdbvalue = gdb.parse_and_eval("$PINCE_PATH")
PINCE_PATH = gdbvalue.string()
sys.path.append(PINCE_PATH)  # Adds the PINCE directory to PYTHONPATH to import libraries from PINCE

from libPINCE.gdb_python_scripts import ScriptUtils
from libPINCE import SysUtils
from libPINCE import type_defs

inferior = gdb.selected_inferior()
pid = inferior.pid
recv_file = SysUtils.get_ipc_from_PINCE_file(pid)
send_file = SysUtils.get_ipc_to_PINCE_file(pid)

if str(gdb.parse_and_eval("$rax")) == "void":
    current_arch = type_defs.INFERIOR_ARCH.ARCH_32
else:
    current_arch = type_defs.INFERIOR_ARCH.ARCH_64

# Format of info_list: [count, previous_pc_address, register_info, float_info, disas_info]
# Format of watchpoint_dict: {address1:info_list1, address2:info_list2, ...}
# Format of watchpoint_numbers: str([1,2,3,4,..])
# Format: {watchpoint_numbers1:watchpoint_dict1, watchpoint_numbers2:track_watchpoint_dict2, ...}
track_watchpoint_dict = {}

# Format of expression_info_dict: {value1:count1, value2:count2, ...}
# Format of register_expression_dict: {expression1:expression_info_dict1, expression2:expression_info_dict2, ...}
# Format: {breakpoint_number1:register_expression_dict1, breakpoint_number2:register_expression_dict2, ...}
track_breakpoint_dict = {}


def receive_from_pince():
    return pickle.load(open(recv_file, "rb"))


def send_to_pince(contents_send):
    pickle.dump(contents_send, open(send_file, "wb"))


class ReadMultipleAddresses(gdb.Command):
    def __init__(self):
        super(ReadMultipleAddresses, self).__init__("pince-read-multiple-addresses", gdb.COMMAND_USER)

    def invoke(self, arg, from_tty):
        contents_send = []
        contents_recv = receive_from_pince()

        # contents_recv format: [[address1, index1, length1, unicode1, zero_terminate1],[address2, ...], ...]
        for item in contents_recv:
            address = item[0]
            index = item[1]
            try:
                length = item[2]
            except IndexError:
                length = 0
            try:
                unicode = item[3]
            except IndexError:
                unicode = False
            try:
                zero_terminate = item[4]
            except IndexError:
                zero_terminate = True
            data_read = ScriptUtils.read_single_address(address, index, length, unicode, zero_terminate)
            contents_send.append(data_read)
        send_to_pince(contents_send)


class SetMultipleAddresses(gdb.Command):
    def __init__(self):
        super(SetMultipleAddresses, self).__init__("pince-set-multiple-addresses", gdb.COMMAND_USER)

    def invoke(self, arg, from_tty):
        contents_recv = receive_from_pince()

        # last item of contents_recv is always value, so we pop it from the list first
        value = contents_recv.pop()

        # contents_recv format after popping the value: [[address1, index1],[address2, index2], ...]
        for item in contents_recv:
            address = item[0]
            index = item[1]

            '''
            The reason we do the check here instead of inside of the function set_single_address() is because try/except
            block doesn't work in function set_single_address() when writing something to file in /proc/$pid/mem. Python
            is normally capable of catching IOError exception, but I have no idea about why it doesn't work in function
            set_single_address()
            '''
            try:
                ScriptUtils.set_single_address(address, index, value)
            except IOError:
                print("Can't access the address " + address if type(address) == str else hex(address))
                pass


class ReadSingleAddress(gdb.Command):
    def __init__(self):
        super(ReadSingleAddress, self).__init__("pince-read-single-address", gdb.COMMAND_USER)

    def invoke(self, arg, from_tty):
        contents_recv = receive_from_pince()
        address = contents_recv[0]
        value_index = contents_recv[1]
        length = contents_recv[2]
        is_unicode = contents_recv[3]
        zero_terminate = contents_recv[4]
        contents_send = ScriptUtils.read_single_address(address, value_index, length, is_unicode, zero_terminate)
        send_to_pince(contents_send)


class IgnoreErrors(gdb.Command):
    def __init__(self):
        super(IgnoreErrors, self).__init__("ignore-errors", gdb.COMMAND_USER)

    def invoke(self, arg, from_tty):
        try:
            gdb.execute(arg, from_tty)
        except:
            pass


class CLIOutput(gdb.Command):
    def __init__(self):
        super(CLIOutput, self).__init__("cli-output", gdb.COMMAND_USER)

    def invoke(self, arg, from_tty):
        try:
            contents_send = gdb.execute(arg, from_tty, to_string=True)
        except Exception as e:
            contents_send = str(e)
        print(contents_send)
        send_to_pince(contents_send)


class ParseConvenienceVariables(gdb.Command):
    def __init__(self):
        super(ParseConvenienceVariables, self).__init__("pince-parse-convenience-variables", gdb.COMMAND_USER)

    def invoke(self, arg, from_tty):
        contents_send = []
        contents_recv = receive_from_pince()
        for item in contents_recv:
            try:
                value = gdb.parse_and_eval(item)
                parsed_value = str(value)
            except:
                parsed_value = None
            contents_send.append(parsed_value)
        send_to_pince(contents_send)


class ReadRegisters(gdb.Command):
    def __init__(self):
        super(ReadRegisters, self).__init__("pince-read-registers", gdb.COMMAND_USER)

    def invoke(self, arg, from_tty):
        contents_send = ScriptUtils.get_general_registers()
        contents_send.update(ScriptUtils.get_flag_registers())
        contents_send.update(ScriptUtils.get_segment_registers())
        send_to_pince(contents_send)


class ReadFloatRegisters(gdb.Command):
    def __init__(self):
        super(ReadFloatRegisters, self).__init__("pince-read-float-registers", gdb.COMMAND_USER)

    def invoke(self, arg, from_tty):
        contents_send = ScriptUtils.get_float_registers()
        send_to_pince(contents_send)


class GetStackTraceInfo(gdb.Command):
    def __init__(self):
        super(GetStackTraceInfo, self).__init__("pince-get-stack-trace-info", gdb.COMMAND_USER)

    def invoke(self, arg, from_tty):
        contents_send = []
        if current_arch == type_defs.INFERIOR_ARCH.ARCH_64:
            sp_register = "rsp"
            result = gdb.execute("p/x $rsp", from_tty, to_string=True)
        else:
            sp_register = "esp"
            result = gdb.execute("p/x $esp", from_tty, to_string=True)
        stack_pointer_int = int(re.search(r"0x[0-9a-fA-F]+", result).group(0), 16)  # $6 = 0x7f0bc0b6bb40
        result = gdb.execute("bt", from_tty, to_string=True)

        # Example: #10 0x000000000040c45a in--->#10--->10
        max_frame = re.findall(r"#\d+\s+0x[0-9a-fA-F]+\s+in", result)[-1].split()[0].replace("#", "")

        # +1 because frame numbers start from 0
        for item in range(int(max_frame) + 1):
            result = gdb.execute("info frame " + str(item), from_tty, to_string=True)

            # frame at 0x7ffe1e989950--->0x7ffe1e989950
            frame_address = re.search(r"frame\s+at\s+0x[0-9a-fA-F]+", result).group(0).split()[-1]
            difference = hex(int(frame_address, 16) - stack_pointer_int)
            frame_address_with_difference = frame_address + "(" + sp_register + "+" + difference + ")"

            # saved rip = 0x7f633a853fe4
            return_address = re.search(r"saved.*=\s+0x[0-9a-fA-F]+", result)
            if return_address:
                return_address = return_address.group(0).split()[-1]
                result = gdb.execute("x/b " + return_address, from_tty, to_string=True)

                # 0x40c431 <_start>:--->0x40c431 <_start>
                return_address_with_info = re.search(r"0x[0-9a-fA-F]+.*:", result).group(0).split(":")[0]
            else:
                return_address_with_info = "<unavailable>"
            contents_send.append([return_address_with_info, frame_address_with_difference])
        send_to_pince(contents_send)


class GetStackInfo(gdb.Command):
    def __init__(self):
        super(GetStackInfo, self).__init__("pince-get-stack-info", gdb.COMMAND_USER)

    def invoke(self, arg, from_tty):
        contents_send = []
        if current_arch == type_defs.INFERIOR_ARCH.ARCH_64:
            chunk_size = 8
            float_format = "d"
            stack_register = "rsp"
            result = gdb.execute("p/x $rsp", from_tty, to_string=True)
        else:
            chunk_size = 4
            float_format = "f"
            stack_register = "esp"
            result = gdb.execute("p/x $esp", from_tty, to_string=True)
        stack_address = int(re.search(r"0x[0-9a-fA-F]+", result).group(0), 16)  # $6 = 0x7f0bc0b6bb40
        mem_file = "/proc/" + str(pid) + "/mem"
        with open(mem_file, "rb") as FILE:
            FILE.seek(stack_address)
            for index in range(int(4096 / chunk_size)):
                current_offset = chunk_size * index
                stack_indicator = hex(stack_address + current_offset) + "(" + stack_register + "+" + hex(
                    current_offset) + ")"
                try:
                    read = FILE.read(chunk_size)
                except:
                    print("Can't access the stack after address " + stack_indicator)
                    break
                hex_data = "0x" + "".join(format(n, '02x') for n in reversed(read))
                int_data = str(int(hex_data, 16))
                float_data = str(struct.unpack_from(float_format, read)[0])
                contents_send.append([stack_indicator, hex_data, int_data, float_data])
        send_to_pince(contents_send)


class GetFrameReturnAddresses(gdb.Command):
    def __init__(self):
        super(GetFrameReturnAddresses, self).__init__("pince-get-frame-return-addresses", gdb.COMMAND_USER)

    def invoke(self, arg, from_tty):
        contents_send = []
        result = gdb.execute("bt", from_tty, to_string=True)

        # Example: #10 0x000000000040c45a in--->#10--->10
        max_frame = re.findall(r"#\d+\s+0x[0-9a-fA-F]+\s+in", result)[-1].split()[0].replace("#", "")

        # +1 because frame numbers start from 0
        for item in range(int(max_frame) + 1):
            result = gdb.execute("info frame " + str(item), from_tty, to_string=True)

            # saved rip = 0x7f633a853fe4
            return_address = re.search(r"saved.*=\s+0x[0-9a-fA-F]+", result)
            if return_address:
                return_address = return_address.group(0).split()[-1]
                result = gdb.execute("x/b " + return_address, from_tty, to_string=True)

                # 0x40c431 <_start>:--->0x40c431 <_start>
                return_address_with_info = re.search(r"0x[0-9a-fA-F]+.*:", result).group(0).split(":")[0]
            else:
                return_address_with_info = "<unavailable>"
            contents_send.append(return_address_with_info)
        send_to_pince(contents_send)


class GetFrameInfo(gdb.Command):
    def __init__(self):
        super(GetFrameInfo, self).__init__("pince-get-frame-info", gdb.COMMAND_USER)

    def invoke(self, arg, from_tty):
        contents_recv = receive_from_pince()
        result = gdb.execute("bt", from_tty, to_string=True)

        # Example: #10 0x000000000040c45a in--->#10--->10
        max_frame = re.findall(r"#\d+\s+0x[0-9a-fA-F]+\s+in", result)[-1].split()[0].replace("#", "")
        if 0 <= int(contents_recv) <= int(max_frame):
            contents_send = gdb.execute("info frame " + contents_recv, from_tty, to_string=True)
        else:
            print("Frame " + contents_recv + " doesn't exist")
            contents_send = None
        send_to_pince(contents_send)


class HexDump(gdb.Command):
    def __init__(self):
        super(HexDump, self).__init__("pince-hex-dump", gdb.COMMAND_USER)

    def invoke(self, arg, from_tty):
        contents_recv = receive_from_pince()
        contents_send = []
        address = contents_recv[0]
        offset = contents_recv[1]
        mem_file = "/proc/" + str(pid) + "/mem"
        with open(mem_file, "rb") as FILE:
            FILE.seek(address)
            for item in range(offset):
                try:
                    current_item = " ".join(format(n, '02x') for n in FILE.read(1))
                except IOError:
                    current_item = "??"
                    FILE.seek(1, io.SEEK_CUR)  # Necessary since read() failed to execute
                contents_send.append(current_item)
        send_to_pince(contents_send)


class GetTrackWatchpointInfo(gdb.Command):
    def __init__(self):
        super(GetTrackWatchpointInfo, self).__init__("pince-get-track-watchpoint-info", gdb.COMMAND_USER)

    def invoke(self, arg, from_tty):
        breakpoints = arg
        current_pc_int = int(SysUtils.extract_address(str(gdb.parse_and_eval("$pc"))), 16)
        try:
            disas_output = gdb.execute("disas $pc-30,$pc", to_string=True)

            # Just before the line "End of assembler dump"
            last_instruction = disas_output.splitlines()[-2]
            previous_pc_address = SysUtils.extract_address(last_instruction)
        except:
            previous_pc_address = hex(current_pc_int)
        global track_watchpoint_dict
        try:
            count = track_watchpoint_dict[breakpoints][current_pc_int][0] + 1
        except KeyError:
            if breakpoints not in track_watchpoint_dict:
                track_watchpoint_dict[breakpoints] = OrderedDict()
            count = 1
        register_info = ScriptUtils.get_general_registers()
        register_info.update(ScriptUtils.get_flag_registers())
        register_info.update(ScriptUtils.get_segment_registers())
        float_info = ScriptUtils.get_float_registers()
        disas_info = gdb.execute("disas " + previous_pc_address + ",+40", to_string=True).replace("=>", "  ")
        track_watchpoint_dict[breakpoints][current_pc_int] = [count, previous_pc_address, register_info, float_info,
                                                              disas_info]
        track_watchpoint_file = SysUtils.get_track_watchpoint_file(pid, breakpoints)
        pickle.dump(track_watchpoint_dict[breakpoints], open(track_watchpoint_file, "wb"))


class GetTrackBreakpointInfo(gdb.Command):
    def __init__(self):
        super(GetTrackBreakpointInfo, self).__init__("pince-get-track-breakpoint-info", gdb.COMMAND_USER)

    def invoke(self, arg, from_tty):
        arg_list = arg.split(",")
        breakpoint_number = arg_list.pop()
        register_expressions = arg_list
        global track_breakpoint_dict
        if not breakpoint_number in track_breakpoint_dict:
            track_breakpoint_dict[breakpoint_number] = OrderedDict()
        for register_expression in register_expressions:
            if not register_expression:
                continue
            if not register_expression in track_breakpoint_dict[breakpoint_number]:
                track_breakpoint_dict[breakpoint_number][register_expression] = OrderedDict()
            try:
                address = SysUtils.extract_address(gdb.execute("p/x " + register_expression, from_tty, to_string=True))
            except:
                address = None
            if address:
                if address not in track_breakpoint_dict[breakpoint_number][register_expression]:
                    track_breakpoint_dict[breakpoint_number][register_expression][address] = 1
                else:
                    track_breakpoint_dict[breakpoint_number][register_expression][address] += 1
        track_breakpoint_file = SysUtils.get_track_breakpoint_file(pid, breakpoint_number)
        pickle.dump(track_breakpoint_dict[breakpoint_number], open(track_breakpoint_file, "wb"))


class PhaseOut(gdb.Command):
    def __init__(self):
        super(PhaseOut, self).__init__("phase-out", gdb.COMMAND_USER)

    def invoke(self, arg, from_tty):
        gdb.execute("detach")
        gdb.execute("echo Successfully detached from the target pid: " + str(pid))


class PhaseIn(gdb.Command):
    def __init__(self):
        super(PhaseIn, self).__init__("phase-in", gdb.COMMAND_USER)

    def invoke(self, arg, from_tty):
        gdb.execute("attach " + str(pid))
        gdb.execute("echo Successfully attached back to the target pid: " + str(pid))


class TraceInstructions(gdb.Command):
    def __init__(self):
        super(TraceInstructions, self).__init__("pince-trace-instructions", gdb.COMMAND_USER)

    def invoke(self, arg, from_tty):
        breakpoint, max_trace_count, stop_condition, step_mode, stop_after_trace,collect_general_registers,\
        collect_flag_registers, collect_segment_registers, collect_float_registers = eval(arg)
        gdb.execute("delete " + breakpoint)
        regex_ret = re.compile(r":\s+ret")  # 0x7f71a4dc5ff8 <poll+72>:	ret
        regex_call = re.compile(r":\s+call")  # 0x7f71a4dc5fe4 <poll+52>:	call   0x7f71a4de1100
        contents_send = type_defs.TraceInstructionsTree()
        for x in range(max_trace_count):
            line_info = gdb.execute("x/i $pc", to_string=True).split(maxsplit=1)[1]
            collect_dict = OrderedDict()
            if collect_general_registers:
                collect_dict.update(ScriptUtils.get_general_registers())
            if collect_flag_registers:
                collect_dict.update(ScriptUtils.get_flag_registers())
            if collect_segment_registers:
                collect_dict.update(ScriptUtils.get_segment_registers())
            if collect_float_registers:
                collect_dict.update(ScriptUtils.get_float_registers())
            contents_send.add_child(type_defs.TraceInstructionsTree(line_info, collect_dict))
            status_info = (type_defs.TRACE_STATUS.STATUS_TRACING, line_info+" ("+str(x+1)+"/"+str(max_trace_count)+")")
            trace_status_file = SysUtils.get_trace_instructions_status_file(pid, breakpoint)
            pickle.dump(status_info, open(trace_status_file, "wb"))
            if regex_ret.search(line_info):
                if contents_send.parent is None:
                    new_parent=type_defs.TraceInstructionsTree()
                    contents_send.set_parent(new_parent)
                    new_parent.add_child(contents_send)
                contents_send = contents_send.parent
            elif step_mode == type_defs.STEP_MODE.SINGLE_STEP:
                if regex_call.search(line_info):
                    contents_send = contents_send.children[-1]
            if stop_condition:
                try:
                    if str(gdb.parse_and_eval(stop_condition)) == "1":
                        break
                except:
                    pass
            if step_mode == type_defs.STEP_MODE.SINGLE_STEP:
                gdb.execute("stepi", to_string=True)
            elif step_mode == type_defs.STEP_MODE.STEP_OVER:
                gdb.execute("nexti", to_string=True)
        trace_instructions_file = SysUtils.get_trace_instructions_file(pid, breakpoint)
        pickle.dump(contents_send.get_root(), open(trace_instructions_file, "wb"))
        status_info = (type_defs.TRACE_STATUS.STATUS_FINISHED,"Tracing has been completed")
        trace_status_file = SysUtils.get_trace_instructions_status_file(pid, breakpoint)
        pickle.dump(status_info, open(trace_status_file, "wb"))
        if not stop_after_trace:
            gdb.execute("c")


IgnoreErrors()
CLIOutput()
ReadMultipleAddresses()
SetMultipleAddresses()
ReadSingleAddress()
ParseConvenienceVariables()
ReadRegisters()
ReadFloatRegisters()
GetStackTraceInfo()
GetStackInfo()
GetFrameReturnAddresses()
GetFrameInfo()
HexDump()
GetTrackWatchpointInfo()
GetTrackBreakpointInfo()
PhaseOut()
PhaseIn()
TraceInstructions()
