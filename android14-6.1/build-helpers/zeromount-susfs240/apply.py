#!/usr/bin/env python3
"""Bounded Guard6.13 version-literal compatibility patch, not a source rebuild."""
from pathlib import Path
import argparse,hashlib,json,struct

INPUT_SHA256='1a0b25246a54746ebe89fb210ffbc8217f6227d9f5a04e964630e50228bea036'
SUSFS_240_PIN='a2165b6f875b73e2f87d3c6f12814efac8de061d'
WORDS={0x1bcd40:(0x72a665ca,0x72a685ca),0x1bcd5c:(0x72a5c66a,0x72a5c68a)}
DATA=((b'SUSFS-2.3.0-LP64',b'SUSFS-2.4.0-LP64'),
      (b'supported: v2.3.0',b'supported: v2.4.0'),
      (b'Add one official SUSFS v2.3.0 OPEN_REDIRECT rule',b'Add one official SUSFS v2.4.0 OPEN_REDIRECT rule'))

def sha(data):return hashlib.sha256(data).hexdigest()
def sections(data):
 if data[:6]!=b'\x7fELF\x02\x01':raise RuntimeError('ELF64 little-endian required')
 e=struct.unpack_from('<16sHHIQQQIHHHHHH',data)
 if e[2]!=183:raise RuntimeError('AArch64 required')
 raw=[struct.unpack_from('<IIQQQQIIQQ',data,e[6]+i*e[11]) for i in range(e[12])]
 strings=raw[e[13]];strings=data[strings[4]:strings[4]+strings[5]]
 return {strings[s[0]:].split(b'\0',1)[0].decode():s for s in raw}

def expected_versions(data):
 """Decode the two actual AArch64 MOV/MOVK literal pairs, without rewriting branches."""
 def imm(offset,expected_opcode):
  word=struct.unpack_from('<I',data,offset)[0]
  if word & ~0x1fffe0 != expected_opcode:raise RuntimeError('Unexpected version literal instruction')
  return (word>>5)&0xffff
 six=imm(0x1bcd38,0x5280000a)|(imm(0x1bcd40,0x72a0000a)<<16)
 suffix=imm(0x1bcd48,0x52800008)
 five=imm(0x1bcd54,0x5280000a)|(imm(0x1bcd5c,0x72a0000a)<<16)
 last=imm(0x1bcd64,0x52800008)
 return [six.to_bytes(4,'little')+suffix.to_bytes(2,'little'),five.to_bytes(4,'little')+bytes([last])]

def apply(data):
 if sha(data)!=INPUT_SHA256:raise RuntimeError('Exact independently tested Guard6.13 native core required')
 table=sections(data);text=table['.text'];rodata=table['.rodata']
 if text[2]&4!=4 or rodata[2]&5!=0:raise RuntimeError('Executable/read-only section protection mismatch')
 if expected_versions(data)!=[b'v2.3.0',b'2.3.0']:raise RuntimeError('Original strict version gate changed')
 out=bytearray(data);edits=[]
 for offset,(old,new) in WORDS.items():
  if not(text[4]<=offset<text[4]+text[5]):raise RuntimeError('Instruction outside .text')
  if struct.unpack_from('<I',data,offset)[0]!=old:raise RuntimeError('Unexpected literal instruction')
  # Only the 16-bit immediate field differs; opcode/register/shift are invariant.
  if old & ~0x1fffe0 != new & ~0x1fffe0:raise RuntimeError('Instruction semantics changed beyond literal')
  struct.pack_into('<I',out,offset,new)
  edits.append({'section':'.text','offset':offset,'old_word':hex(old),'new_word':hex(new),'meaning':'MOVK w10: exact version string digit 3 -> 4'})
 for old,new in DATA:
  if len(old)!=len(new) or data.count(old)!=1:raise RuntimeError('Ambiguous version label')
  offset=data.index(old)
  if not(rodata[4]<=offset and offset+len(old)<=rodata[4]+rodata[5]):raise RuntimeError('Version label outside .rodata')
  out[offset:offset+len(old)]=new
  edits.append({'section':'.rodata','offset':offset,'old':old.decode(),'new':new.decode()})
 out=bytes(out)
 if expected_versions(out)!=[b'v2.4.0',b'2.4.0']:raise RuntimeError('Patched strict version gate mismatch')
 differences=[i for i,(a,b) in enumerate(zip(data,out)) if a!=b]
 if len(differences)!=5 or len(data)!=len(out):raise RuntimeError('Patch exceeded five audited byte changes')
 normalized=bytearray(out)
 for i in differences:normalized[i]=data[i]
 if bytes(normalized)!=data:raise RuntimeError('Unrelated ELF bytes changed')
 original_text=data[text[4]:text[4]+text[5]]
 patched_text=bytearray(out[text[4]:text[4]+text[5]])
 for offset,(old,_) in WORDS.items():struct.pack_into('<I',patched_text,offset-text[4],old)
 if bytes(patched_text)!=original_text:raise RuntimeError('Unrelated executable instruction changed')
 receipt={'schema':1,'kind':'bounded binary version-literal compatibility patch; not source rebuild',
  'input_sha256':sha(data),'output_sha256':sha(out),'bytes':len(out),'changed_byte_offsets':differences,
  'executable_instruction_changes':2,'unrelated_executable_bytes_changed':False,
  'all_other_elf_bytes_identical':True,'branch_and_call_instructions_unchanged':True,
  'accepted_versions':['v2.4.0','2.4.0'],'unknown_versions_remain_rejected':True,
  'susfs_240_upstream_pin':SUSFS_240_PIN,'susfs_240_delta':'version macro/module metadata only; LP64 structures and command numbers unchanged',
  'native_historical_build_and_audited_commit_metadata_preserved':True,'edits':edits,
  'kernel_or_module_installed_by_tool':False}
 return out,receipt

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('input',type=Path);p.add_argument('output',type=Path);p.add_argument('--receipt',type=Path,required=True);a=p.parse_args()
 if a.input.resolve()==a.output.resolve():raise RuntimeError('Input must remain untouched')
 result,proof=apply(a.input.read_bytes())
 if a.output.exists() and a.output.read_bytes()!=result:raise RuntimeError('Refusing to overwrite unrelated output')
 a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_bytes(result)
 a.receipt.parent.mkdir(parents=True,exist_ok=True);a.receipt.write_text(json.dumps(proof,indent=2)+'\n')
 print(json.dumps({k:v for k,v in proof.items() if k!='edits'},indent=2))
if __name__=='__main__':main()
