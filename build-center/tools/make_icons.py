"""Generate small application icons without external image assets."""
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'.build-deps'))
from PIL import Image,ImageDraw,ImageFont

image=Image.new('RGB',(512,512),'#1c2b22');draw=ImageDraw.Draw(image)
draw.rounded_rectangle((73,73,439,439),radius=74,fill='#2a3a28',outline='#8cba72',width=5)
for p in (160,224,288,352):
    for coords in ((p,28,p,53),(p,459,p,484),(28,p,53,p),(459,p,484,p)):
        draw.line(coords,fill='#6c8d59',width=12)
font_path=Path('C:/Windows/Fonts/segoeuiz.ttf')
font=ImageFont.truetype(str(font_path),175) if font_path.exists() else ImageFont.load_default(size=150)
draw.text((246,248),'SU',font=font,anchor='mm',fill='#b7ed93',stroke_width=1)
for size in (192,512):image.resize((size,size),Image.Resampling.LANCZOS).save(ROOT/f'web/icon-{size}.png')
res=ROOT/'android/res/drawable';res.mkdir(parents=True,exist_ok=True)
image.save(res/'icon.png')
image.save(ROOT/'tools/icon.ico',sizes=[(16,16),(32,32),(48,48),(64,64),(128,128),(256,256)])
print('Icons generated')
