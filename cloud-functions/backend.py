"""JMComic core: no downloader mutation, global image capture or self-proxy."""
import io
import math
import os
import re
from urllib.parse import urlsplit

from flask import jsonify, request
from jmcomic import JmOption, JmImageTool, JmModuleConfig
from PIL import Image
from runtime import create_app, ApiError, public_url, memoize, download, serve

app = create_app(__name__)


def client():
    options = {"client": {"impl": os.environ.get("JM_CLIENT", "api"),
        "retry_times": 0, "postman": {"meta_data": {"timeout": 4}}}}
    if os.environ.get("JM_DOMAINS"):
        options["client"]["domain"] = os.environ["JM_DOMAINS"].split(",")[:3]
    cookie = request.headers.get("Cookie")
    if cookie:
        from http.cookies import SimpleCookie
        parsed = SimpleCookie()
        parsed.load(cookie)
        options["client"]["postman"]["meta_data"]["cookies"] = {key:item.value for key,item in parsed.items()}
    value = JmOption.construct(options).new_jm_client()
    if not cookie and os.environ.get("JM_USERNAME") and os.environ.get("JM_PASSWORD"):
        value.login(os.environ["JM_USERNAME"], os.environ["JM_PASSWORD"])
    return value


@memoize(600)
def album_data(item_id):
    album = client().get_album_detail(item_id)
    return {"id":item_id,"name":album.name,"pages":album.page_count,"views":album.views,
            "tags":album.tags,"episodes":[list(item) for item in album.episode_list]}


@memoize(600)
def photo_data(photo_id):
    photo = client().get_photo_detail(photo_id)
    return {"name":photo.name,"images":[{"url":image.img_url,"scramble":image.scramble_id,
            "aid":image.aid,"filename":image.img_file_name} for image in photo]}


def decoded_page(photo_id, page):
    info = photo_data(photo_id)
    if not 1 <= page <= len(info["images"]):
        raise ApiError(404,"Page not found")
    item = info["images"][page-1]
    data = download(item["url"], {"User-Agent":"Mozilla/5.0"})
    with Image.open(io.BytesIO(data)) as original:
        if original.width*original.height>int(os.environ.get("MAX_IMAGE_PIXELS","32000000")):
            raise ApiError(413,"原图超过像素预算")
        original.load()
        num = JmImageTool.get_num(item["scramble"],item["aid"],item["filename"])
        if num == 0:
            return original.copy()
        w,h = original.size
        decoded = Image.new("RGB",(w,h))
        over = h%num
        for i in range(num):
            move = math.floor(h/num)
            y_src,y_dst = h-move*(i+1)-over,move*i
            if i == 0:
                move += over
            else:
                y_dst += over
            with original.crop((0,y_src,w,y_src+move)) as stripe:
                decoded.paste(stripe,(0,y_dst))
        return decoded


@app.get("/")
@app.get("/health")
def health():
    return jsonify(status="ok",source="JMComic")


@app.get("/config")
@app.get("/config/")
def config():
    return jsonify({"JMComic":{"name":"JMComic","apiUrl":public_url(),"detailPath":"/album/<id>",
        "photoPath":"/photo/<id>/chapter/<chapter>","searchPath":"/search/<text>/<page>","type":"jmcomic","idType":"numeric"}})


@app.get("/album/<int:item_id>")
@app.get("/album/<int:item_id>/")
def album(item_id):
    info = album_data(item_id)
    return jsonify(item_id=item_id,name=info["name"],page_count=info["pages"],views=info["views"],
        tags=info["tags"],total_chapters=len(info["episodes"]),cover=public_url()+f"/album/{item_id}/cover")


@app.get("/album/<int:item_id>/cover")
def cover(item_id):
    domain = JmModuleConfig.DOMAIN_IMAGE_LIST[0]
    return serve(["cover",item_id],lambda:download(f"https://{domain}/media/albums/{item_id}_3x4.jpg"),200)


@memoize(60)
def search_data(value,page):
    upstream_size = JmModuleConfig.PAGE_SIZE_SEARCH
    offset = (page-1)*10
    upstream_page = offset//upstream_size+1
    result = client().search_site(search_query=value,page=upstream_page)
    all_items = [{"comic_id":aid,"title":title,"pages":0} for aid,title in result]
    return {"page":page,"has_more":page*10<result.total,"results":all_items[offset%upstream_size:offset%upstream_size+10]}


@app.get("/search/<value>")
@app.get("/search/<value>/")
@app.get("/search/<value>/<int:page>")
def search(value,page=1):
    if page<1 or not value.strip():
        raise ApiError(400,"无效关键词或页码")
    result = search_data(value,page)
    for item in result["results"]:
        item["cover_url"] = public_url()+f"/album/{item['comic_id']}/cover"
    return jsonify(result)


@app.get("/photo/<int:item_id>/chapter/<int:chapter>")
def photo_list(item_id,chapter):
    info = album_data(item_id)
    if not 1<=chapter<=len(info["episodes"]):
        raise ApiError(404,"Chapter not found")
    photo_id = info["episodes"][chapter-1][0]
    photo = photo_data(photo_id)
    return jsonify(title=photo["name"],images=[{"url":public_url()+f"/photo/{photo_id}/{photo_id}_{page}.jpg"}
        for page in range(1,len(photo["images"])+1)])


@app.get("/photo/<int:item_id>")
@app.get("/photo/<int:item_id>/")
@app.get("/photo/<int:item_id>/<page>")
def image(item_id,page="0_1.jpg"):
    match = re.fullmatch(r"(?:\d+_)?([1-9]\d*)(?:\.jpg)?",page)
    if not match:
        raise ApiError(400,"无效页码")
    number = int(match[1])
    return serve(["page",item_id,number],lambda:decoded_page(item_id,number))


@app.get("/image/proxy")
def legacy_proxy():
    url = request.args.get("url","")
    # Old lists wrapped our own route. Resolve it locally, without HTTP/encoding twice.
    match = re.fullmatch(r"/photo/(\d+)/(?:\d+_)?([1-9]\d*)\.jpg",urlsplit(url).path)
    if match:
        return image(int(match[1]),match[2])
    if not url:
        raise ApiError(400,"缺少 url")
    return serve(["proxy",url],lambda:download(url))


@app.errorhandler(Exception)
def unexpected(error):
    if isinstance(error,ApiError):
        return jsonify(code=error.status,message=error.message),error.status
    from werkzeug.exceptions import HTTPException
    status = error.code if isinstance(error,HTTPException) else 502
    return jsonify(code=status,message="路由未找到" if status==404 else "JMComic 上游请求或解析失败"),status
