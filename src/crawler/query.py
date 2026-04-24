"""余票查询：选港口/日期/票种后提交查询，返回班次列表"""
import datetime
import time
from typing import Optional

from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.common.action_chains import ActionChains

SITE_URL = "https://pc.ssky123.com/online_booking_pc/#/index"
TICKET_URL = "https://pc.ssky123.com/online_booking_pc/#/ticket"
WAIT_TIMEOUT = 15


def query_tickets(
    driver: WebDriver,
    departure_num: int,
    destination_num: int,
    travel_date: str,
    ticket_type: str = "旅客",
    departure_name: str = "",
    destination_name: str = "",
    log_fn=None,
) -> list:
    """
    在首页查询余票。
    travel_date: "YYYY-MM-DD" 格式
    返回班次列表，每个元素: {
        trip_num, depart_time, ship_type, status, seats, book_element
    }
    """
    def log(msg, level="INFO"):
        if log_fn:
            log_fn(level, msg)

    driver.get(SITE_URL)
    wait = WebDriverWait(driver, WAIT_TIMEOUT)

    # 等待购票区域加载
    wait.until(
        EC.presence_of_element_located((By.XPATH, "//div[contains(@class,'index__place')]"))
    )
    time.sleep(0.5)

    # ── 选票种（必须先选，因为不同票种显示不同的 index__place）──────
    log(f"选择票种：{ticket_type}")
    _select_ticket_type(driver, wait, ticket_type, log)
    time.sleep(0.3)

    # ── 选出发港 ─────────────────────────────────────────────
    if departure_name:
        log(f"选择出发港：{departure_name}")
        _select_port(driver, wait, "出发港口", departure_name, log)
        time.sleep(0.5)

    # ── 选到达港 ─────────────────────────────────────────────
    if destination_name:
        log(f"选择到达港：{destination_name}")
        _select_port(driver, wait, "到达港口", destination_name, log)
        time.sleep(0.5)

    # ── 选日期 ────────────────────────────────────────────────
    log(f"选择日期：{travel_date}")
    _select_date(driver, wait, travel_date, log)
    time.sleep(0.3)

    # ── 点查询 ────────────────────────────────────────────────
    log("点击查询按钮")
    # 查询按钮：<button class="q-btn ... search ..."><div>查询</div></button>
    search_btn = wait.until(
        EC.element_to_be_clickable(
            (By.XPATH, "//button[contains(@class,'search')]")
        )
    )
    search_btn.click()

    # ── 等待跳转到结果页 ──────────────────────────────────────
    wait.until(EC.url_contains("#/ticket"))
    time.sleep(1)

    # ── 解析结果 ─────────────────────────────────────────────
    results = _parse_results(driver, wait, log)
    log(f"查询完成，共 {len(results)} 个班次可预订")
    return results


def _select_ticket_type(driver: WebDriver, wait: WebDriverWait, ticket_type: str, log):
    """
    选择票种。
    页面结构：<p class="isactive">旅客</p>  <p class="">小客车及随车人员</p>
    class="isactive" 表示已选中，点击对应文字即可切换。
    """
    try:
        btn = driver.find_element(By.XPATH, f"//p[text()='{ticket_type}']")
        if "isactive" not in (btn.get_attribute("class") or ""):
            btn.click()
            time.sleep(0.3)
    except Exception as e:
        log(f"选择票种失败：{e}", "WARN")


def _select_port(driver: WebDriver, wait: WebDriverWait, label: str, port_name: str, log):
    """
    选择出发港或到达港。
    label: "出发港口" 或 "到达港口"
    port_name: 如 "嵊泗(泗礁)"

    页面结构（可见的 index__place 行）：
      <div class="row index__place">
        <div class="col-md-4" style="cursor:pointer">
          <p>嵊泗(泗礁)</p>
          <p>出发港口</p>        ← label
        </div>
        <div class="col-md-4">...(交换箭头)...</div>
        <div class="col-md-4" style="cursor:pointer">
          <p>嵊泗(枸杞)</p>
          <p>到达港口</p>        ← label
        </div>
      </div>
    """
    try:
        # 找到可见的 index__place 行中包含目标 label 的 col-md-4
        port_div = driver.find_element(
            By.XPATH,
            f"//div[contains(@class,'index__place') and not(contains(@style,'display: none'))]"
            f"//p[text()='{label}']/parent::div"
        )
        # 检查是否已是目标港口
        current_port_p = port_div.find_element(By.XPATH, "./p[1]")
        if current_port_p.text.strip() == port_name:
            return  # 已经是目标港口，无需操作

        # 点击打开港口选择器
        port_div.click()
        time.sleep(1)

        # 等待港口选择弹窗（在 modal-content 里找港口名）
        try:
            target_port = wait.until(
                EC.element_to_be_clickable(
                    (By.XPATH,
                     f"//div[contains(@class,'modal-content')]//*[text()='{port_name}']"
                     f" | //div[contains(@class,'modal')][not(contains(@style,'display: none'))]"
                     f"//*[text()='{port_name}']")
                )
            )
            target_port.click()
        except Exception:
            # 备选：全页面找到目标港口文字并点击（弹窗可能是行内渲染）
            candidates = driver.find_elements(By.XPATH, f"//*[text()='{port_name}']")
            # 过滤掉 index__place 中原来显示的文字（那个是触发源，不是选项）
            for c in candidates:
                parent_class = c.find_element(By.XPATH, "..").get_attribute("class") or ""
                if "index__place" not in parent_class:
                    c.click()
                    break
        time.sleep(0.5)
    except Exception as e:
        log(f"选择{label}({port_name})失败：{e}", "WARN")


def _select_date(driver: WebDriver, wait: WebDriverWait, travel_date: str, log):
    """
    选择出行日期（YYYY-MM-DD 格式）。

    页面日历结构（calendar-dropdown，初始 display:none）：
      <div class="calendar-dropdown" style="...display: none;">
        <section class="wh_container">
          <div class="wh_top_changge">
            <li><div class="wh_jiantou1"></div></li>   ← 上一月
            <li class="wh_content_li">2026年4月</li>
            <li><div class="wh_jiantou2"></div></li>   ← 下一月
          </div>
          <div class="wh_content">...星期标题...</div>
          <div class="wh_content">
            <div class="wh_content_item">
              <div class="wh_item_date [wh_other_dayhide] [wh_want_dayhide]">28</div>
            </div>
            ...
          </div>
        </section>
      </div>

    wh_other_dayhide = 非本月日期（上/下月溢出格）
    wh_want_dayhide  = 已过期/不可选日期
    """
    try:
        target = datetime.datetime.strptime(travel_date, "%Y-%m-%d").date()
        target_year = target.year
        target_month = target.month
        target_day = target.day

        # 点击日期显示区域触发日历展开
        # <p style="...border-bottom: 1px solid rgb(102, 102, 102)...">4月28日(周二) <span>&gt;</span></p>
        date_trigger = driver.find_element(
            By.XPATH,
            "//div[contains(@class,'index__date')]//p[contains(@style,'border-bottom')]"
        )
        date_trigger.click()
        time.sleep(0.5)

        # 等待日历容器出现（移除 display:none 后可见）
        cal = wait.until(
            EC.visibility_of_element_located(
                (By.XPATH, "//div[contains(@class,'calendar-dropdown')]")
            )
        )

        # 翻月到目标月份（最多翻 24 次）
        for _ in range(24):
            month_text = cal.find_element(By.XPATH, ".//li[@class='wh_content_li']").text.strip()
            # 格式：2026年4月
            parts = month_text.replace("年", "-").replace("月", "").split("-")
            cur_year, cur_month = int(parts[0]), int(parts[1])
            if cur_year == target_year and cur_month == target_month:
                break
            if (cur_year, cur_month) < (target_year, target_month):
                cal.find_element(By.XPATH, ".//div[@class='wh_jiantou2']").click()
            else:
                cal.find_element(By.XPATH, ".//div[@class='wh_jiantou1']").click()
            time.sleep(0.3)

        # 点击目标日期（排除非本月的溢出格）
        day_el = cal.find_element(
            By.XPATH,
            f".//div[contains(@class,'wh_item_date')"
            f" and not(contains(@class,'wh_other_dayhide'))"
            f" and text()='{target_day}']"
        )
        day_el.click()
        time.sleep(0.3)
    except Exception as e:
        log(f"选择日期失败：{e}", "WARN")


def _parse_results(driver: WebDriver, wait: WebDriverWait, log) -> list:
    """
    解析票务结果页的班次列表。

    结果页 URL：#/ticket
    每个班次行结构（div with height 116px）：
      p[1]  = 航次，如 "11080次"
      p[2]  = 开船时间，如 "08:00"
      p[3]  = 开车时间，如 "----"（或具体时间）
      p[4]  = 船类型，如 "高速客船"
      p[5]  = 出发港/到达港（含 span）
      p[6]  = 舱位等级（含 ul.seatClassesletter）
      p[7]  = 航班状态，如 "正常"
      p[8]  = 预订按钮列（含 span "预订"）
    """
    results = []
    try:
        # 等待班次列表出现
        wait.until(
            EC.presence_of_element_located((By.XPATH, "//div[@class='list__content']"))
        )
        time.sleep(0.5)

        rows = driver.find_elements(
            By.XPATH,
            "//div[@class='list__content']//div[contains(@style,'height: 116px')]"
        )

        for row in rows:
            try:
                p_tags = row.find_elements(By.XPATH, "./p")
                if len(p_tags) < 7:
                    continue

                trip_num = p_tags[0].text.strip()        # "11080次"
                depart_time = p_tags[1].text.strip()     # "08:00"
                ship_type = p_tags[3].text.strip()       # "高速客船"
                status = p_tags[6].text.strip()          # "正常" / "已售完"

                # 解析舱位余票
                seats = {}
                try:
                    seat_items = row.find_elements(
                        By.XPATH, ".//ul[@class='seatClassesletter']/li"
                    )
                    for li in seat_items:
                        li_text = li.text.strip()       # "上舱：3张"
                        spans = li.find_elements(By.XPATH, ".//span")
                        if spans:
                            count = int(spans[0].text.strip())
                            seat_name = li_text.split("：")[0] if "：" in li_text else li_text
                            seats[seat_name] = count
                except Exception:
                    pass

                # 找预订 span
                book_spans = row.find_elements(
                    By.XPATH, ".//span[text()='预订']"
                )
                if not book_spans:
                    continue  # 无预订按钮 = 该班次不可预订（售罄/已过/关闭）

                total_remain = sum(seats.values()) if seats else 1
                results.append({
                    "trip_num": trip_num,
                    "depart_time": depart_time,
                    "ship_type": ship_type,
                    "status": status,
                    "seats": seats,
                    "remain": total_remain,
                    "element": row,                 # 整行 WebElement
                    "book_element": book_spans[0],  # 预订 span
                })
            except Exception as e:
                log(f"解析班次行失败：{e}", "WARN")
    except Exception as e:
        log(f"解析查询结果失败：{e}", "WARN")
    return results


def find_available_trip(
    trips: list,
    preferred_seat: str = "",       # 向后兼容：单舱位名称
    preferred_seats: list = None,   # 新：多舱位名称列表
    sail_time_from: str = "",       # 开航时间起（"HH:MM"），空=不限
    sail_time_to: str = "",         # 开航时间止（"HH:MM"），空=不限
    require_vehicle: bool = False,  # 是否需要同时检查车辆余票（小客车票）
) -> Optional[dict]:
    """
    从班次列表中找到合适的班次。
    preferred_seats: 优先舱位名称列表；优先返回包含任一指定舱位有余票的班次，无则降级。
    sail_time_from/to: 仅返回开航时间在范围内的班次。
    require_vehicle: 为 True 时还要求 driverSeatClass 中有公开车辆余票。
    """
    # 统一处理舱位参数（兼容旧版 preferred_seat）
    seats_wanted: list = preferred_seats if preferred_seats is not None else (
        [preferred_seat] if preferred_seat else []
    )

    def in_time_range(trip) -> bool:
        sail = trip.get("sailTime") or trip.get("sail_time", "")
        if not sail:
            return True  # 无时间信息，不过滤
        if sail_time_from and sail < sail_time_from:
            return False
        if sail_time_to and sail > sail_time_to:
            return False
        return True

    def _is_api(trip) -> bool:
        return "seatClasses" in trip or "onSale" in trip

    def _vehicle_ok(trip) -> bool:
        """车辆余票检测：driverSeatClass 中任意一项 pubCurrentCount > 0"""
        if not require_vehicle:
            return True
        car_seats = trip.get("driverSeatClass") or []
        if isinstance(car_seats, dict):
            car_seats = [car_seats]
        return any(sc.get("pubCurrentCount", 0) > 0 for sc in car_seats)

    def is_ok(trip) -> bool:
        if _is_api(trip):
            if not trip.get("onSale", 1):
                return False
            return any(
                sc.get("pubCurrentCount", 0) > 0
                for sc in (trip.get("seatClasses") or [])
            )
        return trip.get("remain", 0) > 0

    def seat_ok(trip) -> bool:
        if not seats_wanted:
            return True
        if _is_api(trip):
            return any(
                sc.get("className") in seats_wanted and
                sc.get("pubCurrentCount", 0) > 0
                for sc in (trip.get("seatClasses") or [])
            )
        return any(trip.get("seats", {}).get(s, 0) > 0 for s in seats_wanted)

    def status_ok(trip) -> bool:
        if _is_api(trip):
            return bool(trip.get("onSale", 1))
        return trip.get("status") == "正常"

    # 第一轮：时间范围内 + 状态正常 + 指定舱位有票 + 车辆有票
    for trip in trips:
        if in_time_range(trip) and status_ok(trip) and is_ok(trip) and seat_ok(trip) and _vehicle_ok(trip):
            return trip

    # 第二轮：时间范围内 + 指定舱位有票 + 车辆有票（不限状态）
    if seats_wanted:
        for trip in trips:
            if in_time_range(trip) and is_ok(trip) and seat_ok(trip) and _vehicle_ok(trip):
                return trip

    # 第三轮：时间范围内 + 任意有票班次（仅无舱位偏好时使用，避免以错误舱位下单）
    if not seats_wanted:
        for trip in trips:
            if in_time_range(trip) and status_ok(trip) and is_ok(trip) and _vehicle_ok(trip):
                return trip

        for trip in trips:
            if in_time_range(trip) and is_ok(trip) and _vehicle_ok(trip):
                return trip

    return None
