"""Collecte des produits du site avec Selenium.

Exemples :
    python src/scraper.py                              # toutes les catégories
    python src/scraper.py --categories Face Lips --headless
    python src/scraper.py --max-products 10            # essai rapide

Sortie : data/raw/produits_AAAA-MM-JJ.csv, une ligne par produit (catégorie, prix, note, avis visibles,
ingrédients, labels, best-seller). L'analyse se trouve dans notebooks/analyse.ipynb.
"""
import argparse
import logging
import random
import time
from datetime import date
from html import unescape
from pathlib import Path

import pandas as pd
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.common.exceptions import TimeoutException, WebDriverException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait


# ---------------------------------------------------------------- paramètres
BASE_URL = "https://www.sheglam.com/"
BEST_SELLERS_URL = "https://www.sheglam.com/collection/Best-Sellers-30003?sort=most_popular"

# Délais (en secondes) entre deux actions, pour ne pas surcharger le site
DELAY_SHORT = (1.0, 2.0)
DELAY_PAGE = (4.0, 6.0)
TIMEOUT = 40
RETRIES = 2

# Menus principaux (XPath) et onglet « cheveux »
MAIN_CATEGORIES = {
    "Face": "//div[contains(@class,'fun-pc-sheglam-menu-item')]//span[contains(text(),'Face')]",
    "Eyes": "//div[contains(@class,'fun-pc-sheglam-menu-item')]//span[contains(text(),'Eyes')]",
    "Lips": "//div[contains(@class,'fun-pc-sheglam-menu-item')]//span[contains(text(),'Lips')]",
    "Tools & Others": "//div[contains(@class,'fun-pc-sheglam-menu-item')]//span[contains(text(),'Tools')]",
}
HAIR_TAB = "//div[contains(@class,'fun-pc-sg-home-tab-tabItem') and contains(text(),'SHEGLAM HAIR')]"
HAIR_CATEGORIES = {
    "Hair Tools": "//span[contains(@class,'fun-pc-sg-bcc-menu-menuTitle') and contains(text(),'Hot Tools')]",
    "Hair Care": "//span[contains(@class,'fun-pc-sg-bcc-menu-menuTitle') and contains(text(),'Hair Care')]",
}
NO_INGREDIENTS = {"Tools & Others", "Hair Tools"}

# Sélecteurs CSS
SEL = {
    "menu": "//div[contains(@class,'fun-pc-sheglam-menu-item')]",
    "cookie": ".cookie-accept-button",
    "product": ".fun-pc-sg-goods-cell-wrapper",
    "name": ".fun-pc-sg-goods-cell-name",
    "price": ".fun-pc-sg-goods-cell-salePrice",
    "star": ".fun-pc-std-rate-active",
    "show_more": ".fun-pc-std-list-showMore button",
    "review": "fun-pc-sg-review-item-wrapper",
    "gallery": "fun-pc-std-gallery-thumbnails",
    "image": "fun-pc-image-img",
    "collapse": "fun-pc-std-collapse-wrapper",
    "label": ".style_label__chEXT",
    "ingredients": ".fun-pc-ellipsis-wrapper div",
    "plug": "//div[contains(@class,'style_mainAttrTitle__OV5Ab')]/span[contains(text(),'Plug(Voltage):')]/following-sibling::span",
}

# Mots-clés du nom de produit -> sous-catégorie (le premier mot-clé trouvé l'emporte)
SUBCATEGORIES = {
    "Face": {
        "Primer": ["primer", "pore", "sunburst"],
        "Concealer": ["concealer"],
        "Foundation": ["foundation"],
        "Blush": ["blush", "festive", "cheeky", "use balm", "lip cream"],
        "Highlighter": ["highlighter", "highlighting", "glow stick", "shimmer", "eye pencil"],
        "Setting Spray": ["spray"],
        "Powder": ["powder"],
        "Palette": ["palette"],
        "Contour & Bronzer": ["bronzer", "contour", "tan", "sun", "pen-light", "dark", "nude", "sand", "bronzing"],
    },
    "Eyes": {
        "Eyeliner": ["eyeliner", "liner", "wand"],
        "Eyeshadow": ["eyeshadow", "tone shadow", "jelly", "glitter", "flake"],
        "Eyeshadow Palette": ["palette", "stack"],
        "Mascara": ["mascara"],
        "Eyebrow": ["brow", "eyebrow", "control hair"],
        "Lashes": ["lash", "lashes"],
        "Eye Primer": ["under eye"],
    },
    "Lips": {
        "Lipstick": ["lipstick", "lip set", "stacks"],
        "Lip Gloss": ["gloss", "hydra jelly", "care", "mask", "oil", "soft", "jam"],
        "Lip Liner": ["liner", "marker", "duo"],
        "Lip Balm": ["balm"],
        "Lip Kit": ["kit"],
        "Lip Plumper": ["lip plumper"],
        "Lip Tint": ["lip tint", "cheek tint"],
    },
    "Tools & Others": {
        "Brush Set": ["brush set"],
        "Brush": ["brush"],
        "Sponge": ["sponge"],
        "Puff": ["puff"],
        "Makeup Bag": ["bag"],
        "Mirror": ["mirror"],
        "Brush Cleaner": ["cleaner"],
        "Eyelash Tool": ["eyelash"],
        "Eyelash Curler": ["curler"],
        "Brows & Lash Tools": ["mermaid"],
        "Facial Cleaning Tools": ["mattifying"],
        "Eyelashes and Adhesives Kits": ["magnetizing eyes"],
    },
    "Hair Tools": {
        "Hair Straightener Iron": ["straightener"],
        "Hot-Air Brushes & Straight Hair Combs": ["sleek", "blowout", "straight-combs"],
        "Curling Tongs & Curling Wands": ["curler", "curling", "curl", "iron"],
    },
    "Hair Care": {
        "Hair Treatment": ["thermal", "glow", "leave-in", "oil"],
        "Hair Coloring": ["dye"],
        "Styling Products": ["hold"],
    },
}


def subcategory(name, category):
    """Sous-catégorie d'un produit à partir des mots de son nom."""
    low = name.lower()
    for sub, keywords in SUBCATEGORIES.get(category, {}).items():
        if any(k in low for k in keywords):
            return sub
    return "Autre"


log = logging.getLogger("scraper")


def pause(bounds):
    time.sleep(random.uniform(*bounds))


def retry(times=RETRIES):
    """Relance une fonction en cas d'erreur Selenium, avec une pause entre deux essais."""
    def deco(fn):
        def wrapper(*args, **kwargs):
            for attempt in range(1, times + 2):
                try:
                    return fn(*args, **kwargs)
                except (TimeoutException, WebDriverException) as e:
                    log.warning("%s : essai %d échoué (%s)", fn.__name__, attempt, type(e).__name__)
                    if attempt > times:
                        raise
                    pause(DELAY_PAGE)
        return wrapper
    return deco


class Scraper:
    def __init__(self, headless=False, max_products=None):
        opts = Options()
        if headless:
            opts.add_argument("--headless=new")
        opts.add_argument("--disable-gpu")
        opts.add_argument("--disable-dev-shm-usage")
        opts.add_argument("--window-size=1400,1000")
        self.driver = webdriver.Chrome(options=opts)
        self.wait = WebDriverWait(self.driver, TIMEOUT)
        self.max_products = max_products

    def close(self):
        self.driver.quit()

    # ---------- navigation ----------
    @retry()
    def open_home(self):
        self.driver.get(BASE_URL)
        pause(DELAY_PAGE)
        try:
            WebDriverWait(self.driver, 8).until(EC.element_to_be_clickable((By.CSS_SELECTOR, SEL["cookie"]))).click()
        except TimeoutException:
            log.info("Pas de bandeau cookies.")

    def click(self, xpath):
        el = self.wait.until(EC.element_to_be_clickable((By.XPATH, xpath)))
        self.driver.execute_script("arguments[0].scrollIntoView(true); arguments[0].click();", el)
        pause(DELAY_SHORT)

    def show_all(self):
        """Clique sur « voir plus » jusqu'à ce que tous les produits soient affichés."""
        while True:
            try:
                btn = WebDriverWait(self.driver, 8).until(EC.element_to_be_clickable((By.CSS_SELECTOR, SEL["show_more"])))
                self.driver.execute_script("arguments[0].click()", btn)
                pause(DELAY_SHORT)
            except TimeoutException:
                return

    # ---------- extraction ----------
    @staticmethod
    def card_info(card):
        info = {"Name": None, "Price": None, "Stars": None}
        try:
            info["Name"] = unescape(card.find_element(By.CSS_SELECTOR, SEL["name"]).text.strip())
        except WebDriverException:
            pass
        try:
            info["Price"] = card.find_element(By.CSS_SELECTOR, SEL["price"]).text.strip()
        except WebDriverException:
            pass
        stars = card.find_elements(By.CSS_SELECTOR, SEL["star"])
        if stars:
            total = 0.0
            for s in stars:
                style = s.get_attribute("style") or ""
                if ":" in style:
                    total += float(style.split(":")[1].replace("%", "").replace(";", "")) / 100
            info["Stars"] = round(total, 1)
        return info

    def product_page(self, href, category):
        """Ouvre la fiche produit dans un nouvel onglet : avis visibles, images, ingrédients, labels."""
        main = self.driver.current_window_handle
        self.driver.execute_script("window.open(arguments[0])", href)
        self.driver.switch_to.window(self.driver.window_handles[-1])
        try:
            pause(DELAY_PAGE)
            self.driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            pause(DELAY_SHORT)
            soup = BeautifulSoup(self.driver.page_source, "html.parser")
            out = {"Reviews": [], "Image URLs": [], "Ingredients": None, "Labels": [], "Plug": None}
            for r in soup.find_all("div", class_=SEL["review"]):
                content = r.find("div", class_="fun-pc-sg-review-item-content")
                date_ = r.find("div", class_="fun-pc-sg-review-item-date")
                out["Reviews"].append({"date": date_.text.strip() if date_ else None,
                                       "content": content.text.strip() if content else None,
                                       "stars": len(r.find_all("span", class_="fun-pc-std-rate-active"))})
            gallery = soup.find("div", class_=SEL["gallery"])
            if gallery:
                for img in gallery.find_all("img", class_=SEL["image"]):
                    src = img.get("src") or ""
                    out["Image URLs"].append("https:" + src if src.startswith("//") else src)
            if category not in NO_INGREDIENTS:
                block = soup.find("span", string="Ingredients")
                box = block.find_parent("div", class_=SEL["collapse"]) if block else None
                if box:
                    out["Labels"] = [d.get_text(strip=True) for d in box.select(SEL["label"])]
                    ing = box.select_one(SEL["ingredients"])
                    out["Ingredients"] = ing.get_text(strip=True) if ing else None
            if category == "Hair Tools":
                plug = self.driver.find_elements(By.XPATH, SEL["plug"])
                out["Plug"] = plug[0].text.strip() if plug else None
            return out
        finally:
            self.driver.close()
            self.driver.switch_to.window(main)

    def scrape_listing(self, category):
        """Tous les produits de la page de catégorie ouverte."""
        self.wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, SEL["product"])))
        self.show_all()
        cards = self.driver.find_elements(By.CSS_SELECTOR, SEL["product"])
        if self.max_products:
            cards = cards[: self.max_products]
        log.info("%s : %d produits", category, len(cards))
        rows = []
        for i, card in enumerate(cards, 1):
            try:
                self.driver.execute_script("arguments[0].scrollIntoView()", card)
                info = self.card_info(card)
                href = card.find_element(By.TAG_NAME, "a").get_attribute("href")
                details = retry()(self.product_page)(href, category)
                rows.append({"Category": category, **info, "Subcategory": subcategory(info["Name"] or "", category),
                             "URL": href, **details})
            except Exception as e:  # un produit en erreur ne doit pas arrêter la collecte
                log.error("%s, produit %d ignoré : %s", category, i, e)
        return rows

    def scrape_categories(self, categories):
        rows = []
        for cat in categories:
            try:
                if cat in MAIN_CATEGORIES:
                    self.open_home()
                    self.wait.until(EC.presence_of_element_located((By.XPATH, SEL["menu"])))
                    self.click(MAIN_CATEGORIES[cat])
                else:
                    self.open_home()
                    self.click(HAIR_TAB)
                    self.click(HAIR_CATEGORIES[cat])
                rows += self.scrape_listing(cat)
            except Exception as e:
                log.error("Catégorie %s abandonnée : %s", cat, e)
        return rows

    @retry()
    def best_sellers(self):
        self.driver.get(BEST_SELLERS_URL)
        pause(DELAY_PAGE)
        self.show_all()
        names = set()
        for card in self.driver.find_elements(By.CSS_SELECTOR, SEL["product"]):
            try:
                names.add(normalize(card.find_element(By.CSS_SELECTOR, SEL["name"]).get_attribute("textContent")))
            except WebDriverException:
                continue
        log.info("%d best-sellers", len(names))
        return names


def normalize(name):
    return " ".join(unescape(str(name)).lower().split())


def main(argv=None):
    all_cats = list(MAIN_CATEGORIES) + list(HAIR_CATEGORIES)
    p = argparse.ArgumentParser(description="Collecte des produits cosmétiques")
    p.add_argument("--categories", nargs="+", default=all_cats, choices=all_cats)
    p.add_argument("--headless", action="store_true", help="navigateur sans fenêtre")
    p.add_argument("--max-products", type=int, default=None, help="limite par catégorie (essais)")
    p.add_argument("--out", default="data/raw")
    a = p.parse_args(argv)

    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        handlers=[logging.StreamHandler(), logging.FileHandler(out / "scraping.log", encoding="utf-8")])

    s = Scraper(headless=a.headless, max_products=a.max_products)
    try:
        rows = s.scrape_categories(a.categories)
        best = s.best_sellers()
    finally:
        s.close()

    df = pd.DataFrame(rows)
    if df.empty:
        log.error("Aucun produit collecté.")
        return 1
    df["Best Seller"] = df["Name"].map(lambda n: int(normalize(n) in best))
    df = df.drop_duplicates(subset=["Category", "Name", "Price"])
    path = out / f"produits_{date.today():%Y-%m-%d}.csv"
    df.to_csv(path, index=False)
    log.info("%d produits enregistrés dans %s", len(df), path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
