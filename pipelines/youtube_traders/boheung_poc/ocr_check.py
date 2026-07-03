import sys, warnings
warnings.filterwarnings("ignore")
from PIL import Image
from paddleocr import PaddleOCR
ocr = PaddleOCR(lang="korean", use_doc_orientation_classify=False, use_doc_unwarping=False, use_textline_orientation=False, enable_mkldnn=False)
for f in ["frames/f16.png","frames/f40.png","frames/f180.png"]:
    im = Image.open(f); w,h = im.size
    crop = im.crop((0, int(h*0.80), w, h))  # bottom overlay strip
    cp = f.replace("frames/","crop_")
    crop.save(cp)
    res = ocr.predict(cp)
    print("=====", f, "(%dx%d, overlay strip)"%(w,h))
    for r in res:
        texts = r.get("rec_texts",[]); scores=r.get("rec_scores",[])
        for t,s in zip(texts,scores):
            print("  %.2f  %s"%(s,t))
