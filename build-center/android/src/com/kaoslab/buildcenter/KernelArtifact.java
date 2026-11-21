package com.kaoslab.buildcenter;

import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.util.Enumeration;
import java.util.zip.ZipEntry;
import java.util.zip.ZipFile;

/** Reads GitHub's STORED ZIP entries with data descriptors through the central directory. */
public final class KernelArtifact {
    private KernelArtifact(){}
    public static final class Payload {
        public final byte[] bytes;
        public final String filename;
        private Payload(byte[] bytes,String filename){this.bytes=bytes;this.filename=filename;}
    }
    public static Payload unpack(byte[] archive,File cacheDirectory,int limit)throws IOException{
        File temporary=File.createTempFile("kernel-artifact-",".zip",cacheDirectory);
        try{
            try(FileOutputStream out=new FileOutputStream(temporary)){out.write(archive);}
            Payload payload=null;
            try(ZipFile zip=new ZipFile(temporary)){
                Enumeration<? extends ZipEntry> entries=zip.entries();
                while(entries.hasMoreElements()){
                    ZipEntry entry=entries.nextElement();String path=entry.getName();
                    if(path.startsWith("/")||path.contains("..")||path.contains("\\"))throw new IOException("Unsicherer ZIP-Pfad.");
                    if(!entry.isDirectory()&&path.endsWith(".zip")){
                        if(payload!=null)throw new IOException("Mehrdeutiges Kernel-Artefakt.");
                        if(entry.getSize()>limit)throw new IOException("ZIP-Eintrag zu groß.");
                        String filename=path.substring(path.lastIndexOf('/')+1);
                        if(!filename.matches("[a-zA-Z0-9._+ -]{1,240}"))throw new IOException("Ungültiger Dateiname.");
                        try(InputStream in=zip.getInputStream(entry);ByteArrayOutputStream out=new ByteArrayOutputStream()){
                            byte[] buffer=new byte[32768];int count;
                            while((count=in.read(buffer))!=-1){
                                if(count>limit-out.size())throw new IOException("ZIP-Eintrag zu groß.");
                                out.write(buffer,0,count);
                            }
                            payload=new Payload(out.toByteArray(),filename);
                        }
                    }
                }
            }
            if(payload==null)throw new IOException("Flashbare Kernel-ZIP fehlt.");
            return payload;
        }finally{temporary.delete();}
    }
}
