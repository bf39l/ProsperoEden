#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Exercise production image-view filling with buffer-backed blacklist entries."""
from pathlib import Path
import subprocess
import tempfile
import sys
source=(Path(sys.argv[1])/'src/video_core/texture_cache/texture_cache.h').read_text()
sig='void TextureCache<P>::FillImageViews('
a=source.index(sig); pos=source.index('{',a)+1; depth=1
while depth:
    depth+=(source[pos]=='{')-(source[pos]=='}'); pos+=1
method=source[a:pos]
preamble=r'''
#include <array>
#include <span>
#include <cassert>
#include <stdexcept>
using ImageId=unsigned; using ImageViewId=unsigned;
constexpr ImageId NULL_IMAGE_ID=0;
constexpr ImageViewId NULL_IMAGE_VIEW_ID=0;
struct ImageViewInOut {unsigned index; ImageViewId id=0; bool blacklist=true;};
struct ImageViewBase {ImageId image_id=0;};
struct Image {unsigned scale_rating=99; bool scaled=true;};
template<class P> struct TextureCache {
    bool has_deleted_images=false;
    std::array<ImageViewBase,4> slot_image_views{{{0},{0},{1},{2}}};
    std::array<Image,3> slot_images;
    unsigned null_scales=0, image_scales=0;
    bool deleted_once=false;
    bool delete_on_visit=false;
    ImageViewId VisitImageView(unsigned index,bool){
        if(delete_on_visit && !deleted_once){has_deleted_images=true;deleted_once=true;}
        return index;
    }
    bool ScaleDown(Image& image){
        if(&image==&slot_images[0]){++null_scales; return false;}
        ++image_scales;
        const bool changed=image.scaled; image.scaled=false; return changed;
    }
    void FillImageViews(std::span<ImageViewInOut>,bool,bool);
};
'''
tests=r'''
int main(){
    for(bool compute:{false,true}){
        TextureCache<int> cache;
        std::array<ImageViewInOut,4> views{{{0},{1},{2},{3}}};
        cache.FillImageViews(views,compute,true);
        if(cache.null_scales) return 10;
        assert(cache.image_scales==4);
        assert(!cache.slot_images[1].scaled && !cache.slot_images[2].scaled);
        assert(cache.slot_images[0].scale_rating==99);
        assert(cache.slot_images[1].scale_rating==0 && cache.slot_images[2].scale_rating==0);
        assert(views[1].id==1); // Valid buffer view remains available to the pipeline.
        cache.delete_on_visit=true;
        cache.FillImageViews(views,compute,true);
        assert(cache.deleted_once && cache.null_scales==0);
        TextureCache<int> no_blacklist;
        no_blacklist.FillImageViews(views,compute,false);
        assert(no_blacklist.image_scales==0 && no_blacklist.null_scales==0);
        TextureCache<int> per_view;
        for(auto& v:views) v.blacklist=false;
        per_view.FillImageViews(views,compute,true);
        assert(per_view.image_scales==0 && per_view.null_scales==0);
    }
}
'''
with tempfile.TemporaryDirectory() as tmp:
    tmp=Path(tmp)
    def run(body,name):
        cpp=tmp/(name+'.cpp'); exe=tmp/name
        cpp.write_text(preamble+'\ntemplate<class P>\n'+body+tests)
        subprocess.run(['c++','-std=c++20','-Wall','-Wextra','-Werror','-fsanitize=address,undefined','-g',str(cpp),'-o',str(exe)],check=True)
        return subprocess.run([str(exe)],check=False).returncode
    assert run(method,'fixed')==0
    guard='                    // Buffer views have no parent image and cannot be resolution-scaled.\n                    if (image_view.image_id == NULL_IMAGE_ID) {\n                        continue;\n                    }\n'
    assert method.count(guard)==1
    assert run(method.replace(guard,''),'original')==10
print('Buffer-view scaling PASS: real FillImageViews, null/buffer/image views, graphics/compute, blacklist controls, deletion retries; original null-scale control reproduced (ASan/UBSan)')
