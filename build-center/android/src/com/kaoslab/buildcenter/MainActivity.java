package com.kaoslab.buildcenter;

import android.app.Activity;
import android.content.ContentValues;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.PackageInfo;
import android.content.pm.PackageManager;
import android.graphics.Color;
import android.net.Uri;
import android.os.Bundle;
import android.provider.MediaStore;
import android.provider.Settings;
import android.security.keystore.KeyGenParameterSpec;
import android.security.keystore.KeyProperties;
import android.util.Base64;
import android.view.WindowInsets;
import android.webkit.JavascriptInterface;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceRequest;
import android.webkit.WebResourceResponse;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import java.io.*;
import java.net.*;
import java.nio.charset.StandardCharsets;
import java.security.KeyStore;
import java.security.MessageDigest;
import java.util.*;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.zip.ZipEntry;
import java.util.zip.ZipInputStream;
import javax.crypto.Cipher;
import javax.crypto.KeyGenerator;
import javax.crypto.SecretKey;
import javax.crypto.spec.GCMParameterSpec;
import javax.net.ssl.HttpsURLConnection;
import org.json.JSONObject;

public class MainActivity extends Activity {
    private static final String HOST="appassets.androidplatform.net";
    private static final int LIMIT=512*1024*1024;
    private static final String CERT="947ae944f3de4ed4c21a7e4f7953ecf351bfa2b36239da37a34111ad29993eef";
    private WebView web;
    private final ExecutorService executor=Executors.newFixedThreadPool(3);
    private boolean destroyed=false;
    private File pendingApk;

    @Override public void onCreate(Bundle state){
        super.onCreate(state);
        final android.content.res.AssetManager localAssets=getApplicationContext().getAssets();
        getWindow().setStatusBarColor(Color.rgb(16,20,25));
        getWindow().setNavigationBarColor(Color.rgb(16,20,25));
        web=new WebView(this);web.setBackgroundColor(Color.rgb(16,20,25));
        android.widget.FrameLayout container=new android.widget.FrameLayout(this);
        container.setBackgroundColor(Color.rgb(16,20,25));
        container.addView(web,new android.widget.FrameLayout.LayoutParams(-1,-1));
        setContentView(container);
        if(android.os.Build.VERSION.SDK_INT>=30){
            getWindow().setDecorFitsSystemWindows(false);
            container.setOnApplyWindowInsetsListener((v,insets)->{
                android.graphics.Insets bars=insets.getInsets(WindowInsets.Type.systemBars()|WindowInsets.Type.displayCutout());
                v.setPadding(bars.left,bars.top,bars.right,Math.max(bars.bottom,insets.getInsets(WindowInsets.Type.ime()).bottom));return insets;
            });
        }
        web.getSettings().setJavaScriptEnabled(true);web.getSettings().setDomStorageEnabled(true);
        web.getSettings().setAllowFileAccess(false);web.getSettings().setAllowContentAccess(false);
        web.getSettings().setMixedContentMode(android.webkit.WebSettings.MIXED_CONTENT_NEVER_ALLOW);
        web.setWebChromeClient(new WebChromeClient());
        web.setWebViewClient(new WebViewClient(){
            @Override public WebResourceResponse shouldInterceptRequest(WebView v,WebResourceRequest req){
                Uri u=req.getUrl();if(!HOST.equals(u.getHost())||!"https".equals(u.getScheme()))return null;
                String path=u.getPath();if("/".equals(path))path="/index.html";
                if(path==null||path.contains("..")||!path.matches("/[a-zA-Z0-9_.-]+"))return empty();
                try{
                    String mime=path.endsWith(".js")?"application/javascript":path.endsWith(".css")?"text/css":path.endsWith(".svg")?"image/svg+xml":path.endsWith(".png")?"image/png":path.endsWith(".webmanifest")?"application/manifest+json":"text/html";
                    Map<String,String> headers=new HashMap<>();headers.put("X-Content-Type-Options","nosniff");
                    headers.put("Content-Security-Policy","default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'none'; frame-src 'none'; object-src 'none'; base-uri 'none'");
                    return new WebResourceResponse(mime,"UTF-8",200,"OK",headers,localAssets.open("web"+path));
                }catch(IOException e){android.util.Log.e("BuildCenter","Asset could not be loaded: "+path,e);return empty();}
            }
            @Override public boolean shouldOverrideUrlLoading(WebView v,WebResourceRequest req){
                Uri uri=req.getUrl();if(HOST.equals(uri.getHost())&&"https".equals(uri.getScheme()))return false;
                if("https".equals(uri.getScheme())){try{startActivity(new Intent(Intent.ACTION_VIEW,uri));}catch(Exception ignored){}}
                return true;
            }
        });
        web.addJavascriptInterface(new Bridge(),"KaosNative");web.loadUrl("https://"+HOST+"/");
    }
    private WebResourceResponse empty(){return new WebResourceResponse("text/plain","UTF-8",404,"Not Found",Collections.emptyMap(),new ByteArrayInputStream(new byte[0]));}
    private void result(String id,JSONObject data){runOnUiThread(()->{if(!destroyed)web.evaluateJavascript("window.__nativeResult("+JSONObject.quote(id)+","+data.toString()+")",null);});}
    private void failure(String id,Exception e){try{result(id,new JSONObject().put("error",e.getMessage()==null?"Anfrage fehlgeschlagen.":e.getMessage()));}catch(Exception ignored){}}
    private SecretKey key() throws Exception {
        KeyStore store=KeyStore.getInstance("AndroidKeyStore");store.load(null);
        if(!store.containsAlias("build-center-token")){
            KeyGenerator gen=KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES,"AndroidKeyStore");
            gen.init(new KeyGenParameterSpec.Builder("build-center-token",KeyProperties.PURPOSE_ENCRYPT|KeyProperties.PURPOSE_DECRYPT)
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM).setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE).build());gen.generateKey();
        }
        return (SecretKey)store.getKey("build-center-token",null);
    }
    public class Bridge {
        @JavascriptInterface public void openExternal(String address){
            try{Uri uri=Uri.parse(address);if(!"https".equals(uri.getScheme()))return;
                runOnUiThread(()->{try{startActivity(new Intent(Intent.ACTION_VIEW,uri));}catch(Exception ignored){}});
            }catch(Exception ignored){}
        }
        @JavascriptInterface public String loadToken(){
            try{
                SharedPreferences prefs=getSharedPreferences("vault",MODE_PRIVATE);String saved=prefs.getString("value","");if(saved.isEmpty())return "";
                Cipher c=Cipher.getInstance("AES/GCM/NoPadding");c.init(Cipher.DECRYPT_MODE,key(),new GCMParameterSpec(128,Base64.decode(prefs.getString("iv",""),Base64.NO_WRAP)));
                return new String(c.doFinal(Base64.decode(saved,Base64.NO_WRAP)),StandardCharsets.UTF_8);
            }catch(Exception e){return "";}
        }
        @JavascriptInterface public void storeToken(String token){
            try{
                SharedPreferences.Editor p=getSharedPreferences("vault",MODE_PRIVATE).edit();
                if(token.isEmpty()){p.clear().apply();return;}
                Cipher c=Cipher.getInstance("AES/GCM/NoPadding");c.init(Cipher.ENCRYPT_MODE,key());
                p.putString("iv",Base64.encodeToString(c.getIV(),Base64.NO_WRAP));p.putString("value",Base64.encodeToString(c.doFinal(token.getBytes(StandardCharsets.UTF_8)),Base64.NO_WRAP));p.apply();
            }catch(Exception e){runOnUiThread(()->android.widget.Toast.makeText(MainActivity.this,"Token konnte nicht gespeichert werden.",android.widget.Toast.LENGTH_LONG).show());}
        }
        @JavascriptInterface public void request(String id,String body){executor.execute(()->{
            try{JSONObject b=new JSONObject(body);Response r=network(b.getString("url"),b.optString("method","GET"),b.optString("token",""),b.optJSONObject("data"),false);
                JSONObject out=new JSONObject().put("status",r.status).put("headers",r.headers);
                out.put("data",r.raw.length==0?JSONObject.NULL:new org.json.JSONTokener(new String(r.raw,StandardCharsets.UTF_8)).nextValue());result(id,out);
            }catch(Exception e){failure(id,e);}
        });}
        @JavascriptInterface public void download(String id,String body){executor.execute(()->{
            try{
                JSONObject b=new JSONObject(body);byte[] raw=network(b.getString("url"),"GET",b.optString("token",""),null,true).raw;
                String expected=b.optString("digest","").replace("sha256:","");
                if(!expected.isEmpty()&&(!expected.matches("[a-f0-9]{64}")||!sha(raw).equals(expected)))throw new IOException("SHA-256-Prüfung fehlgeschlagen.");
                String name=b.getString("filename");if(!name.matches("[a-zA-Z0-9._+ -]{1,240}")||name.equals(".")||name.equals(".."))throw new IOException("Ungültiger Dateiname.");
                String kind=b.optString("kind","file");
                if("kernel-artifact".equals(kind)){
                    if(expected.isEmpty())throw new IOException("Prüfsumme für Kernel-Artefakt fehlt.");
                    byte[][] payload=new byte[1][];String[] filename=new String[1];int found=0;
                    try(ZipInputStream z=new ZipInputStream(new ByteArrayInputStream(raw))){ZipEntry e;while((e=z.getNextEntry())!=null){
                        if(e.getName().startsWith("/")||e.getName().contains("..")||e.getName().contains("\\"))throw new IOException("Unsicherer ZIP-Pfad.");
                        if(!e.isDirectory()&&e.getName().endsWith(".zip")){found++;if(found>1)throw new IOException("Mehrdeutiges Kernel-Artefakt.");payload[0]=read(z,LIMIT);filename[0]=e.getName().substring(e.getName().lastIndexOf('/')+1);}
                    }}
                    if(found!=1)throw new IOException("Flashbare Kernel-ZIP fehlt.");raw=payload[0];name=filename[0];
                    Set<String> entries=new HashSet<>();try(ZipInputStream z=new ZipInputStream(new ByteArrayInputStream(raw))){ZipEntry e;while((e=z.getNextEntry())!=null){entries.add(e.getName());if(e.getSize()>LIMIT)throw new IOException("ZIP-Eintrag zu groß.");}}
                    if(!entries.contains("anykernel.sh")||!entries.contains("STRICT-KMI.txt")||Collections.disjoint(entries,Arrays.asList("Image","Image.gz","Image.gz-dtb","Image.lz4")))throw new IOException("AnyKernel3-/Strict-KMI-Paket unvollständig.");
                }
                boolean install="apk".equals(kind);
                if(install){
                    File apk=new File(getCacheDir(),"manager.apk");try(FileOutputStream out=new FileOutputStream(apk)){out.write(raw);}
                    PackageInfo info=getPackageManager().getPackageArchiveInfo(apk.getPath(),PackageManager.GET_SIGNING_CERTIFICATES);
                    if(info==null||!"com.sukisu.ultra".equals(info.packageName)||info.signingInfo==null||!sha(info.signingInfo.getApkContentsSigners()[0].toByteArray()).equals(CERT)){apk.delete();throw new IOException("APK ist nicht der offiziell signierte SukiSU-Manager.");}
                    pendingApk=apk;runOnUiThread(()->installApk());
                }else{
                    ContentValues values=new ContentValues();values.put(MediaStore.Downloads.DISPLAY_NAME,name);values.put(MediaStore.Downloads.MIME_TYPE,name.endsWith(".zip")?"application/zip":"text/plain");values.put(MediaStore.Downloads.RELATIVE_PATH,"Download/KAOSLAB");values.put(MediaStore.Downloads.IS_PENDING,1);
                    Uri uri=getContentResolver().insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI,values);if(uri==null)throw new IOException("Downloadordner nicht verfügbar.");
                    try(OutputStream out=getContentResolver().openOutputStream(uri)){if(out==null)throw new IOException("Download konnte nicht gespeichert werden.");out.write(raw);}catch(Exception e){getContentResolver().delete(uri,null,null);throw e;}
                    values.clear();values.put(MediaStore.Downloads.IS_PENDING,0);getContentResolver().update(uri,values,null,null);
                }
                result(id,new JSONObject().put("filename",name).put("sha256",sha(raw)).put("install",install));
            }catch(Exception e){failure(id,e);}
        });}
    }
    private void installApk(){
        if(pendingApk==null)return;
        if(!getPackageManager().canRequestPackageInstalls()){
            startActivity(new Intent(Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES,Uri.parse("package:"+getPackageName())));return;
        }
        Intent intent=new Intent(Intent.ACTION_VIEW).setDataAndType(Uri.parse("content://com.kaoslab.buildcenter.files/manager.apk"),"application/vnd.android.package-archive").addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION);
        pendingApk=null;startActivity(intent);
    }
    @Override protected void onResume(){super.onResume();if(pendingApk!=null&&getPackageManager().canRequestPackageInstalls())installApk();}
    private static String sha(byte[] raw)throws Exception{byte[] digest=MessageDigest.getInstance("SHA-256").digest(raw);StringBuilder b=new StringBuilder();for(byte v:digest)b.append(String.format(Locale.ROOT,"%02x",v&255));return b.toString();}
    private static byte[] read(InputStream in,int limit)throws IOException{ByteArrayOutputStream out=new ByteArrayOutputStream();byte[] buf=new byte[32768];int n;while((n=in.read(buf))!=-1){if(out.size()+n>limit)throw new IOException("Download überschreitet das Größenlimit.");out.write(buf,0,n);}return out.toByteArray();}
    private static boolean allowed(URI u,String method,boolean download){
        if(!"https".equals(u.getScheme())||u.getUserInfo()!=null||(u.getPort()!=-1&&u.getPort()!=443))return false;
        String host=u.getHost(),path=u.getRawPath();
        if("POST".equals(method))return "api.github.com".equals(host)&&path.matches("/repos/[\\w.-]+/[\\w.-]+/actions/workflows/build-center\\.yml/dispatches");
        if(!"GET".equals(method))return false;
        if("api.github.com".equals(host))return path.startsWith("/repos/");
        if("gitlab.com".equals(host))return path.startsWith("/api/v4/projects/simonpunk%2Fsusfs4ksu/")||path.startsWith("/simonpunk/susfs4ksu/-/archive/");
        return download&&("github.com".equals(host)||"codeload.github.com".equals(host))&&path.matches("/[\\w.-]+/[\\w.-]+/(releases/download|zip|tar\\.gz)/.+");
    }
    private static class Response{int status;byte[] raw;JSONObject headers=new JSONObject();}
    private static Response network(String address,String method,String token,JSONObject body,boolean binary)throws Exception{
        URI initial=new URI(address);if(!allowed(initial,method,binary))throw new IOException("Netzwerkadresse nicht freigegeben.");
        URL current=initial.toURL();boolean auth=true;
        for(int i=0;i<6;i++){
            HttpsURLConnection c=(HttpsURLConnection)current.openConnection();c.setConnectTimeout(30000);c.setReadTimeout(binary?90000:35000);c.setInstanceFollowRedirects(false);c.setRequestMethod(method);
            c.setRequestProperty("User-Agent","KAOSLAB-SukiSU-Build-Center/1.0");c.setRequestProperty("Accept",binary?"application/octet-stream":"application/vnd.github+json");
            if(auth&&"api.github.com".equals(current.getHost())&&!token.isEmpty())c.setRequestProperty("Authorization","Bearer "+token);
            if(body!=null){c.setDoOutput(true);c.setRequestProperty("Content-Type","application/json");try(OutputStream out=c.getOutputStream()){out.write(body.toString().getBytes(StandardCharsets.UTF_8));}}
            int status=c.getResponseCode();
            if(status>=300&&status<400&&status!=304){URL next=new URL(current,c.getHeaderField("Location"));c.disconnect();if(!"https".equals(next.getProtocol())||next.getUserInfo()!=null)throw new IOException("Unsichere Weiterleitung.");current=next;auth=false;continue;}
            Response r=new Response();r.status=status;for(String key:Arrays.asList("Link","X-RateLimit-Remaining","X-RateLimit-Reset","Retry-After")){String value=c.getHeaderField(key);if(value!=null)r.headers.put(key.toLowerCase(Locale.ROOT),value);}
            try(InputStream in=status>=400?c.getErrorStream():c.getInputStream()){r.raw=in==null?new byte[0]:read(in,binary?LIMIT:8*1024*1024);}finally{c.disconnect();}
            if(binary&&status>=400)throw new IOException("Download fehlgeschlagen (HTTP "+status+").");return r;
        }
        throw new IOException("Zu viele Download-Weiterleitungen.");
    }
    @Override public void onBackPressed(){if(web.canGoBack())web.goBack();else super.onBackPressed();}
    @Override protected void onDestroy(){destroyed=true;executor.shutdownNow();web.removeJavascriptInterface("KaosNative");web.destroy();super.onDestroy();}
}
