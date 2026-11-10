/* SPDX-License-Identifier: GPL-2.0 */
static const char *entries[]={".","..","com.kaoslab.susfstarget","visible.one","com.kaoslab.susfstarget.suffix","visible.two"};
static const char **active_entries=entries;
static int nr_entries=6,checks;
static int backend(struct file *file,struct dir_context *ctx) {
 (void)file;
 while(ctx->pos<nr_entries){int i=ctx->pos;const char*n=active_entries[i];if(!ctx->actor(ctx,n,strlen(n),i,100+i,4))break;ctx->pos=i+1;}
 return 0;
}
static long call_abi(int abi,void *buffer,int size){
 switch(abi){case 0:return sys_old_readdir(7,buffer,size);case 1:return sys_getdents(7,buffer,size);case 2:return sys_getdents64(7,buffer,size);case 3:return compat_sys_old_readdir(7,buffer,size);default:return compat_sys_getdents(7,buffer,size);}
}
static void require(bool ok,const char *message,int abi){checks++;if(!ok){fprintf(stderr,"FAIL %s abi=%d checks=%d\n",message,abi,checks);exit(1);}}
static void run_case(int abi,bool hidden_expected){
 unsigned char data[96];int found=0,total=0,calls=0;bool seen[6]={0};open_file->f_pos=0;
 for(;;){memset(data,0,sizeof(data));long bytes=call_abi(abi,data,sizeof(data));require(bytes>=0,"unexpected syscall error",abi);require(++calls<30,"directory cursor did not terminate",abi);if(!bytes)break;
  size_t pos=0;
  do {
   char *name;unsigned int size;
   if(abi==0){struct old_linux_dirent*d=(void*)data;name=d->d_name;size=sizeof(data);}
   else if(abi==3){struct compat_old_linux_dirent*d=(void*)data;name=d->d_name;size=sizeof(data);}
   else if(abi==2){struct linux_dirent64*d=(void*)(data+pos);name=d->d_name;size=d->d_reclen;require(size>offsetof(struct linux_dirent64,d_name),"bad dirent64 length",abi);}
   else if(abi==4){struct compat_linux_dirent*d=(void*)(data+pos);name=d->d_name;size=d->d_reclen;require(size>offsetof(struct compat_linux_dirent,d_name),"bad compat length",abi);}
   else {struct linux_dirent*d=(void*)(data+pos);name=d->d_name;size=d->d_reclen;require(size>offsetof(struct linux_dirent,d_name),"bad native length",abi);}
   bool known=false;for(int i=0;i<6;i++)if(!strcmp(name,entries[i])){require(!seen[i],"duplicate entry",abi);seen[i]=true;known=true;}
   require(known,"unexpected entry",abi);if(!strcmp(name,entries[2]))found++;total++;pos+=size;
  }while(abi!=0&&abi!=3&&pos<(size_t)bytes);
 }
 require(found==(hidden_expected?0:1),"directory leak or unexpected hiding",abi);
 require(total==nr_entries-(hidden_expected?1:0),"visible neighbors lost",abi);
 for(int i=0;i<nr_entries;i++){
  if(hidden_expected&&!strcmp(active_entries[i],entries[2]))continue;
  bool returned=false;for(int j=0;j<6;j++)if(!strcmp(active_entries[i],entries[j]))returned=seen[j];
  require(returned,"dot entries or visible control lost",abi);
 }
 require(open_file->f_pos==nr_entries,"end position not preserved",abi);
 require(rcu_depth==0,"RCU reader imbalance",abi);
}
int main(void){
 struct super_block sb={0};struct inode inode={.i_sb=&sb};struct dentry parent={.d_name={"Android",7}},dir={.d_name={"data",4},.d_parent=&parent};struct file_operations ops={.iterate_shared=backend,.iterate=backend};struct file file={.f_inode=&inode,.f_path={&dir},.f_op=&ops};open_file=&file;
 for(int abi=0;abi<5;abi++){
  test_uid=10155;marked=true;name_enabled=false;run_case(abi,false);
  name_enabled=true;test_uid=10252;run_case(abi,false);
  test_uid=10155;marked=false;run_case(abi,false);marked=true;
  dir.d_name=(struct qstr){"names",5};run_case(abi,false);dir.d_name=(struct qstr){"data",4};
  parent.d_name=(struct qstr){"AndroidX",8};run_case(abi,false);parent.d_name=(struct qstr){"Android",7};
  test_uid=0;run_case(abi,false);test_uid=101000;run_case(abi,false);
  test_uid=10155;run_case(abi,true);
  dir.d_name=(struct qstr){"obb",3};rename_retry=1;run_case(abi,true);dir.d_name=(struct qstr){"data",4};
  test_uid=110155;run_case(abi,true);test_uid=10155;
  ops.iterate_shared=NULL;run_case(abi,true);ops.iterate_shared=backend;
  /* A trailing hidden entry must preserve previously emitted bytes even
   * when ZeroMount takes its nonnegative-error injection/EOF branch. */
  const char *hidden_tail[]={entries[0],entries[1],entries[3],entries[4],entries[5],entries[2]};
  active_entries=hidden_tail;run_case(abi,true);
  const char *dots_then_hidden[]={entries[0],entries[1],entries[2]};
  active_entries=dots_then_hidden;nr_entries=3;run_case(abi,true);
  const char *hidden_only[]={"com.kaoslab.susfstarget"};active_entries=hidden_only;nr_entries=1;file.f_pos=0;unsigned char b[96];
  require(call_abi(abi,b,sizeof(b))==0,"all-hidden directory should be EOF",abi);require(file.f_pos==1,"all-hidden cursor must advance",abi);require(call_abi(abi,b,sizeof(b))==0,"repeated EOF should terminate",abi);
  active_entries=entries;nr_entries=6;
 }
 printf("PASS exact readdir C checks=%d ABIs=5 small_buffer=96 inode_cache=absent\n",checks);return 0;
}
