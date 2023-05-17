#!/usr/bin/env python3
# - coding: utf-8 --
from selenium.webdriver.common.by import By
from selenium.webdriver.support.wait import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

import PIL.Image
import PIL.ImageDraw

import io
import os
import cv2
import pathlib
import numpy as np
import textwrap
import traceback
import datetime
import pickle
from concurrent import futures

import time
import logging

from selenium_util import create_driver
from pil_util import get_font, draw_text, text_size, alpha_paste
import notify_slack

DATA_PATH = pathlib.Path(os.path.dirname(__file__)).parent / "data"
WINDOW_SIZE_CACHE = DATA_PATH / "window_size.cache"
CACHE_EXPIRE_HOUR = 1

CLOUD_IMAGE_XPATH = '//div[contains(@id, "jmatile_map_")]'

RAINFALL_INTENSITY_LEVEL = [
    # NOTE: 白
    {"func": lambda h, s: (160 < h) & (h < 180) & (s < 20), "value": 1},
    # NOTE: 薄水色
    {"func": lambda h, s: (140 < h) & (h < 150) & (90 < s) & (s < 100), "value": 5},
    # NOTE: 水色
    {"func": lambda h, s: (145 < h) & (h < 155) & (210 < s) & (s < 230), "value": 10},
    # NOTE: 青色
    {"func": lambda h, s: (155 < h) & (h < 165) & (230 < s), "value": 20},
    # NOTE: 黄色
    {"func": lambda h, s: (35 < h) & (h < 45), "value": 30},
    # NOTE: 橙色
    {"func": lambda h, s: (20 < h) & (h < 30), "value": 50},
    # NOTE: 赤色
    {"func": lambda h, s: (0 < h) & (h < 8), "value": 80},
    # NOTE: 紫色
    {"func": lambda h, s: (225 < h) & (h < 235) & (240 < s)},
]


def get_face_map(font_config):
    return {
        "title": get_font(font_config, "JP_MEDIUM", 50),
        "legend": get_font(font_config, "EN_MEDIUM", 30),
        "legend_unit": get_font(font_config, "EN_MEDIUM", 18),
    }


def hide_label_and_icon(driver):
    PARTS_LIST = [
        {"class": "jmatile-map-title", "mode": "none"},
        {"class": "leaflet-bar", "mode": "none"},
        {"class": "leaflet-control-attribution", "mode": "none"},
        {"class": "leaflet-control-scale-line", "mode": "none"},
    ]
    SCRIPT_CHANGE_DISPAY = """
var elements = document.getElementsByClassName("{class_name}")
    for (i = 0; i < elements.length; i++) {{
        elements[i].style.display="{mode}"
    }}
"""

    wait = WebDriverWait(driver, 5)
    for parts in PARTS_LIST:
        wait.until(EC.presence_of_element_located((By.CLASS_NAME, parts["class"])))

    for parts in PARTS_LIST:
        driver.execute_script(
            SCRIPT_CHANGE_DISPAY.format(
                class_name=parts["class"],
                mode=parts["mode"],
            )
        )


def change_setting(driver):
    # driver.find_element(By.XPATH, '//a[contains(@aria-label, "地形を表示")]').click()

    driver.find_element(By.XPATH, '//a[contains(@aria-label, "色の濃さ")]').click()
    driver.find_element(By.XPATH, '//span[contains(text(), "濃い")]').click()

    driver.find_element(By.XPATH, '//a[contains(@aria-label, "地図を切り替え")]').click()
    driver.find_element(By.XPATH, '//span[contains(text(), "地名なし")]').click()


def shape_cloud_display(driver, width, height, is_future):
    change_setting(driver)

    if is_future:
        driver.find_element(
            By.XPATH,
            '//div[@class="jmatile-control"]//div[contains(text(), " +1時間 ")]',
        ).click()

    hide_label_and_icon(driver)


def change_window_size_impl(driver, url, width, height):
    wait = WebDriverWait(driver, 5)

    # NOTE: 雨雲画像がこのサイズになるように，ウィンドウサイズを調整する
    logging.info("target: {width} x {height}".format(width=width, height=height))

    driver.get(url)
    wait.until(EC.presence_of_element_located((By.XPATH, CLOUD_IMAGE_XPATH)))

    # NOTE: まずはサイズを大きめにしておく
    driver.set_window_size(int(height * 2), int(height * 1.5))
    driver.refresh()
    wait.until(EC.presence_of_element_located((By.XPATH, CLOUD_IMAGE_XPATH)))

    # NOTE: 最初に横サイズを調整
    window_size = driver.get_window_size()
    element_size = driver.find_element(By.XPATH, CLOUD_IMAGE_XPATH).size
    logging.info(
        "[current] window: {window_width} x {window_height}, element: {element_width} x {element_height}".format(
            window_width=window_size["width"],
            window_height=window_size["height"],
            element_width=element_size["width"],
            element_height=element_size["height"],
        )
    )
    if element_size["width"] != width:
        target_window_width = window_size["width"] + (width - element_size["width"])
        logging.info(
            "[change] window: {window_width} x {window_height}".format(
                window_width=target_window_width,
                window_height=window_size["height"],
            )
        )
        driver.set_window_size(target_window_width, height)
    driver.refresh()
    wait.until(EC.presence_of_element_located((By.XPATH, CLOUD_IMAGE_XPATH)))
    time.sleep(1)

    # NOTE: 次に縦サイズを調整
    window_size = driver.get_window_size()
    element_size = driver.find_element(By.XPATH, CLOUD_IMAGE_XPATH).size
    logging.info(
        "[current] window: {window_width} x {window_height}, element: {element_width} x {element_height}".format(
            window_width=window_size["width"],
            window_height=window_size["height"],
            element_width=element_size["width"],
            element_height=element_size["height"],
        )
    )
    if element_size["height"] != height:
        target_window_height = window_size["height"] + (height - element_size["height"])
        logging.info(
            "[change] window: {window_width} x {window_height}".format(
                window_width=window_size["width"],
                window_height=target_window_height,
            )
        )
        driver.set_window_size(
            window_size["width"],
            target_window_height,
        )
    driver.refresh()
    wait.until(EC.presence_of_element_located((By.XPATH, CLOUD_IMAGE_XPATH)))
    time.sleep(1)

    window_size = driver.get_window_size()
    element_size = driver.find_element(By.XPATH, CLOUD_IMAGE_XPATH).size
    logging.info(
        "[current] window: {window_width} x {window_height}, element: {element_width} x {element_height}".format(
            window_width=window_size["width"],
            window_height=window_size["height"],
            element_width=element_size["width"],
            element_height=element_size["height"],
        )
    )
    logging.info(
        "size is {status}".format(
            status="OK"
            if (element_size["width"], element_size["height"]) == (width, height)
            else "unmatch"
        )
    )

    return driver.get_window_size()


def change_window_size(driver, url, width, height):
    # NOTE: 雨雲画像のサイズ調整には時間がかかるので，結果をキャッシュして使う
    window_size_map = {}
    try:
        if pathlib.Path(WINDOW_SIZE_CACHE).exists():
            if (
                datetime.datetime.now()
                - datetime.datetime.fromtimestamp(WINDOW_SIZE_CACHE.stat().st_mtime)
            ).seconds < CACHE_EXPIRE_HOUR * 60 * 60:
                with open(WINDOW_SIZE_CACHE, "rb") as f:
                    window_size_map = pickle.load(f)
            else:
                # NOTE: キャッシュの有効期限切れ
                WINDOW_SIZE_CACHE.unlink(missing_ok=True)
    except:
        pass

    if width in window_size_map and height in window_size_map[width]:
        logging.info(
            "change {width} x {height} based on a cache".format(
                width=width, height=height
            )
        )
        driver.set_window_size(
            window_size_map[width][height]["width"],
            window_size_map[width][height]["height"],
        )
        return

    window_size = change_window_size_impl(driver, url, width, height)

    if width in window_size_map:
        window_size_map[width][height] = window_size
    else:
        window_size_map[width] = {height: window_size}
        with open(WINDOW_SIZE_CACHE, "wb") as f:
            pickle.dump(window_size_map, f)


def fetch_cloud_image(driver, url, width, height, is_future=False):
    logging.info("fetch cloud image")

    wait = WebDriverWait(driver, 5)

    driver.get(url)

    wait.until(EC.presence_of_element_located((By.XPATH, CLOUD_IMAGE_XPATH)))

    shape_cloud_display(driver, width, height, is_future)

    wait.until(
        lambda driver: driver.execute_script("return document.readyState") == "complete"
    )
    time.sleep(0.5)

    png_data = driver.find_element(By.XPATH, CLOUD_IMAGE_XPATH).screenshot_as_png

    driver.refresh()

    return png_data


def retouch_cloud_image(png_data):
    logging.info("retouch image")
    gamma = 0.6

    img_rgb = cv2.imdecode(
        np.asarray(bytearray(png_data), dtype=np.uint8), cv2.IMREAD_COLOR
    )

    img_hsv = cv2.cvtColor(img_rgb, cv2.COLOR_BGR2HSV_FULL).astype(np.float32)
    bar = np.zeros((1, len(RAINFALL_INTENSITY_LEVEL), 3))
    h, s, v = cv2.split(img_hsv)

    # NOTE: 降雨強度の色をグレースケール用に変換
    for i, level in enumerate(RAINFALL_INTENSITY_LEVEL):
        color = (
            0,
            80,
            255
            * (
                (
                    float(len(RAINFALL_INTENSITY_LEVEL) - i)
                    / len(RAINFALL_INTENSITY_LEVEL)
                )
                ** gamma
            ),
        )
        img_hsv[level["func"](h, s)] = color
        bar[0][i] = color

    # NOTE: 白地図の色をやや明るめにする
    img_hsv[s < 30, 2] = np.clip(pow(v[(s < 30)], 1.35) * 0.3, 0, 255)

    return (
        PIL.Image.fromarray(
            cv2.cvtColor(
                cv2.cvtColor(img_hsv.astype(np.uint8), cv2.COLOR_HSV2RGB_FULL),
                cv2.COLOR_RGB2RGBA,
            )
        ),
        PIL.Image.fromarray(
            cv2.cvtColor(
                cv2.cvtColor(bar.astype(np.uint8), cv2.COLOR_HSV2RGB_FULL),
                cv2.COLOR_RGB2RGBA,
            )
        ),
    )


def draw_equidistant_circle(img):
    logging.info("draw equidistant_circle")
    draw = PIL.ImageDraw.Draw(img)
    x = img.size[0] / 2
    y = img.size[1] / 2

    size = 20
    draw.ellipse(
        (x - size / 2, y - size / 2, x + size / 2, y + size / 2),
        fill=(255, 255, 255),
        outline=(60, 60, 60),
        width=5,
    )
    # 5km
    size = 328
    draw.ellipse(
        (x - size / 2, y - size / 2, x + size / 2, y + size / 2),
        outline=(255, 255, 255),
        width=16,
    )
    size = 322
    draw.ellipse(
        (x - size / 2, y - size / 2, x + size / 2, y + size / 2),
        outline=(180, 180, 180),
        width=10,
    )

    return img


def draw_caption(img, title, face_map):
    logging.info("draw caption")
    size = face_map["title"].getsize(title)
    x = 12
    y = 12
    padding = 10
    radius = 20
    alpha = 200

    overlay = PIL.Image.new("RGBA", img.size, (255, 255, 255, 0))
    draw = PIL.ImageDraw.Draw(overlay)
    draw.rectangle(
        (
            x - padding,
            y - padding,
            x + size[0] + padding - radius,
            y + size[1] + padding / 2,
        ),
        fill=(255, 255, 255, alpha),
    )
    draw.rectangle(
        (x - padding, y - padding, x + size[0] + padding, y + padding / 2),
        fill=(255, 255, 255, alpha),
    )

    draw.rounded_rectangle(
        (x - padding, y - padding, x + size[0] + padding, y + size[1] + padding / 2),
        fill=(255, 255, 255, alpha),
        radius=radius,
    )
    img = PIL.Image.alpha_composite(img, overlay)
    draw_text(
        img,
        title,
        (10, 20),
        face_map["title"],
        "left",
        color="#000",
    )

    return img


def create_rain_cloud_img(panel_config, sub_panel_config, face_map, slack_config):
    logging.info(
        "create rain cloud image ({type})".format(
            type="future" if sub_panel_config["is_future"] else "current"
        )
    )
    # NOTE: 同時アクセスを避ける
    if sub_panel_config["is_future"]:
        time.sleep(2)

    driver = create_driver()
    change_window_size(
        driver,
        panel_config["DATA"]["JMA"]["URL"],
        int(panel_config["PANEL"]["WIDTH"] / 2),
        panel_config["PANEL"]["HEIGHT"],
    )

    img = None
    try:
        img = fetch_cloud_image(
            driver,
            panel_config["DATA"]["JMA"]["URL"],
            int(panel_config["PANEL"]["WIDTH"] / 2),
            panel_config["PANEL"]["HEIGHT"],
            sub_panel_config["is_future"],
        )
    except:
        if slack_config is not None:
            notify_slack.error(
                slack_config["BOT_TOKEN"],
                slack_config["ERROR"]["CHANNEL"]["NAME"],
                slack_config["ERROR"]["CHANNEL"]["ID"],
                traceback.format_exc(),
                {
                    "data": PIL.Image.open(
                        (io.BytesIO(driver.get_screenshot_as_png()))
                    ),
                    "text": "エラー時のスクリーンショット",
                },
                interval_min=slack_config["ERROR"]["INTERVAL_MIN"],
            )
        raise

    driver.quit()

    img, bar = retouch_cloud_image(img)
    img = draw_equidistant_circle(img)
    img = draw_caption(img, sub_panel_config["title"], face_map)

    return (img, bar)


def draw_legend(img, bar, panel_config, face_map):
    PADDING = 20
    TEXT_MARGIN = 1.2

    bar_size = panel_config["LEGEND"]["BAR_SIZE"]
    bar = bar.resize(
        (
            bar.size[0] * bar_size,
            bar.size[1] * bar_size,
        ),
        PIL.Image.NEAREST,
    )
    draw = PIL.ImageDraw.Draw(bar)
    for i in range(len(RAINFALL_INTENSITY_LEVEL)):
        draw.rectangle(
            (
                max(bar_size * i - 1, 0),
                0,
                bar_size * (i + 1) - 1,
                bar_size - 1,
            ),
            outline=(20, 20, 20),
        )

    text_height = int(text_size(face_map["legend"], "0")[1] * TEXT_MARGIN)
    unit = "mm/h"
    unit_width, unit_height = text_size(face_map["legend_unit"], unit)
    unit_overlap = text_size(face_map["legend_unit"], unit[0])[0]
    legend = PIL.Image.new(
        "RGBA",
        (
            bar.size[0] + PADDING * 2 + unit_width - unit_overlap,
            bar.size[1] + PADDING * 2 + text_height,
        ),
        (255, 255, 255, 0),
    )
    draw = PIL.ImageDraw.Draw(legend)
    draw.rounded_rectangle(
        (0, 0, legend.size[0], legend.size[1]),
        radius=8,
        fill=(255, 255, 255, 200),
    )

    legend.paste(bar, (PADDING, PADDING + text_height))
    for i in range(len(RAINFALL_INTENSITY_LEVEL)):
        if "value" in RAINFALL_INTENSITY_LEVEL[i]:
            text = str(RAINFALL_INTENSITY_LEVEL[i]["value"])
            pos_x = PADDING + bar_size * (i + 1)
            pos_y = PADDING
            align = "center"
            font = face_map["legend"]
        else:
            text = "mm/h"
            pos_x = PADDING + bar_size * (i + 1) - unit_overlap
            pos_y = PADDING + text_size(face_map["legend"], "0")[1] - unit_height
            align = "left"
            font = face_map["legend_unit"]

        draw_text(
            legend,
            text,
            (
                pos_x,
                pos_y,
            ),
            font,
            align,
            "#666",
        )

    alpha_paste(
        img,
        legend,
        (panel_config["LEGEND"]["OFFSET_X"], panel_config["LEGEND"]["OFFSET_Y"] - 100),
    )

    return img


def create_rain_cloud_panel_impl(config):
    panel_config = config["RAIN_CLOUD"]
    font_config = config["FONT"]

    SUB_PANEL_CONFIG_LIST = [
        {"is_future": False, "title": "現在", "offset_x": 0},
        {
            "is_future": True,
            "title": "１時間後",
            "offset_x": int(panel_config["PANEL"]["WIDTH"] / 2),
        },
    ]

    img = PIL.Image.new(
        "RGBA",
        (panel_config["PANEL"]["WIDTH"], panel_config["PANEL"]["HEIGHT"]),
        (255, 255, 255, 255),
    )
    face_map = get_face_map(font_config)

    task_list = []
    # NOTE: 並列に生成する
    with futures.ThreadPoolExecutor() as executor:
        for sub_panel_config in SUB_PANEL_CONFIG_LIST:
            task_list.append(
                executor.submit(
                    create_rain_cloud_img,
                    panel_config,
                    sub_panel_config,
                    face_map,
                    config["SLACK"] if "SLACK" in config else None,
                )
            )

    for i, sub_panel_config in enumerate(SUB_PANEL_CONFIG_LIST):
        sub_img, bar = task_list[i].result()
        img.paste(sub_img, (sub_panel_config["offset_x"], 0))

    img = draw_legend(img, bar, panel_config, face_map)

    return img


def error_image(config, error_text):
    panel_config = config["RAIN_CLOUD"]

    img = PIL.Image.new(
        "RGBA",
        (panel_config["PANEL"]["WIDTH"], panel_config["PANEL"]["HEIGHT"]),
        (255, 255, 255, 255),
    )

    draw = PIL.ImageDraw.Draw(img)
    draw.rectangle(
        (0, 0, config["PANEL"]["DEVICE"]["WIDTH"], config["PANEL"]["DEVICE"]["HEIGHT"]),
        fill=(255, 255, 255, 255),
    )

    draw_text(
        img,
        "ERROR",
        (10, 10),
        get_font(config["FONT"], "EN_BOLD", 100),
        "left",
        "#666",
    )

    draw_text(
        img,
        "\n".join(textwrap.wrap(error_text, 90)),
        (20, 100),
        get_font(config["FONT"], "EN_MEDIUM", 30),
        "left" "#666",
    )

    return img


def create_rain_cloud_panel(config):
    logging.info("create rain cloud panel")
    start = time.perf_counter()

    error_text = None
    for i in range(5):
        try:
            return (create_rain_cloud_panel_impl(config), time.perf_counter() - start)
        except:
            error_text = traceback.format_exc()
            logging.error(error_text)
            pass
        logging.warn("retry")
        time.sleep(5)

    return (error_image(config, error_text), time.perf_counter() - start)


if __name__ == "__main__":
    import logger
    from config import load_config

    logger.init("test")
    logging.info("Test")

    config = load_config()

    result = create_rain_cloud_panel(config)

    logging.info("elapsed time: {time:.3f} sec".format(time=result[1]))

    result[0].save("test_rain_cloud_panel.png", "PNG")

    print("Finish.")
