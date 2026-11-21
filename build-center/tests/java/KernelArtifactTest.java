import com.kaoslab.buildcenter.KernelArtifact;
import java.io.*;
import java.nio.file.*;
import java.util.*;
import java.util.zip.*;

public class KernelArtifactTest {
    static void reject(Path file,File cache,int limit,String expected)throws Exception{
        try{KernelArtifact.unpack(Files.readAllBytes(file),cache,limit);throw new AssertionError("Expected rejection: "+file);}
        catch(IOException error){if(!error.getMessage().contains(expected))throw error;}
        try(var entries=Files.list(cache.toPath())){if(entries.findAny().isPresent())throw new AssertionError("Temporary archive leaked");}
    }
    public static void main(String[] args)throws Exception{
        Path fixtures=Path.of(args[0]);File cache=fixtures.resolve("cache").toFile();cache.mkdirs();
        byte[] stored=Files.readAllBytes(fixtures.resolve("stored-descriptor.zip"));
        try(ZipInputStream old=new ZipInputStream(new ByteArrayInputStream(stored))){old.getNextEntry();throw new AssertionError("Fixture did not reproduce streaming incompatibility");}
        catch(ZipException expected){if(!expected.getMessage().contains("only DEFLATED"))throw expected;}
        var payload=KernelArtifact.unpack(stored,cache,100000);
        if(!Arrays.equals(payload.bytes,Files.readAllBytes(fixtures.resolve("expected.zip")))||!payload.filename.equals("kernel.zip"))throw new AssertionError("Wrong exact payload");
        var deflated=KernelArtifact.unpack(Files.readAllBytes(fixtures.resolve("deflated.zip")),cache,100000);
        if(!Arrays.equals(payload.bytes,deflated.bytes))throw new AssertionError("Deflated regression");
        reject(fixtures.resolve("multiple.zip"),cache,100000,"Mehrdeutiges");
        reject(fixtures.resolve("traversal.zip"),cache,100000,"Unsicherer");
        reject(fixtures.resolve("missing.zip"),cache,100000,"fehlt");
        reject(fixtures.resolve("large.zip"),cache,10,"groß");
        System.out.println("PASS: stored descriptor reproduction, exact payload, deflated payload, multiple ZIPs, traversal, missing ZIP, size limit, temporary-file cleanup");
    }
}
