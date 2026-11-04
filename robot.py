#!/usr/bin/env python3
"""Robot OutilGraphique.

Toutes les heures (GitHub Actions) :
  1. lit le plan du site (sitemap.xml) et repère les fiches /outil/… ;
     le site mélange deux familles : les OUTILS (pour graphistes) et les projets GRAPHIQUES.
     On ne partage que les projets graphiques. Une fiche est un outil si elle apparaît dans la
     liste « Outil » de l'accueil (les nouveaux outils s'y affichent en premier) ; sinon c'est un graphique ;
  2. lit chaque nouvelle fiche (nom, description, image, date) ;
  3. réécrit feed.xml (flux RSS, lu par Pinterest et tout lecteur RSS) ;
  4. annonce chaque NOUVEAU projet graphique sur Discord (webhook) et l'ajoute à une chaîne Are.na.

Au tout premier passage, il se contente de noter les fiches existantes :
il n'inonde pas Discord ni Are.na avec tout le catalogue.
Aucune dépendance : Python 3 seul.
"""
import html
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from email.utils import format_datetime
from html.parser import HTMLParser
from xml.sax.saxutils import escape

SITE = os.environ.get('SITE', 'https://outilgraphique.framer.website').rstrip('/')
SECTION = '/outil/'
STATE = 'state.json'
FEED = 'feed.xml'
UA = 'OutilGraphique-RSS/1.0 (+https://github.com)'
MAX_ITEMS = 100
# Outils déjà présents le 4 novembre 2026 (la liste de l'accueil n'en montre que les premiers)
OUTILS_CONNUS = {'stochaster', 'tooooools', 'glyphs', 'fontstruct', 'ui-colors', 'the-noun-project', 'lucide-animated',
                 'react-bits', 'endless-tools', 'colorable', 'typescale', 'space-type-generator', 'poussetafonte'}


def get(url):
    req = urllib.request.Request(url, headers={'User-Agent': UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode('utf-8', 'replace')


def post_json(url, data, headers=None):
    body = json.dumps(data).encode()
    req = urllib.request.Request(url, data=body, method='POST', headers={'Content-Type': 'application/json', 'User-Agent': UA, **(headers or {})})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.status


class Meta(HTMLParser):
    """Récupère les balises <meta>, le <title> et le texte visible d'une fiche."""
    def __init__(self):
        super().__init__()
        self.meta, self.title, self._in_title, self.text = {}, '', False, []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == 'meta':
            k = a.get('property') or a.get('name')
            if k and a.get('content') and k not in self.meta:
                self.meta[k] = a['content']
        elif tag == 'title':
            self._in_title = True

    def handle_endtag(self, tag):
        if tag == 'title':
            self._in_title = False

    def handle_data(self, d):
        if self._in_title:
            self.title += d
        elif d.strip():
            self.text.append(d.strip())


MOIS = {'janv': 1, 'févr': 2, 'fevr': 2, 'mars': 3, 'avr': 4, 'mai': 5, 'juin': 6, 'juil': 7, 'août': 8, 'aout': 8, 'sept': 9, 'oct': 10, 'nov': 11, 'déc': 12, 'dec': 12}


def read_tool(url):
    p = Meta()
    p.feed(get(url))
    m = p.meta
    name = (m.get('og:title') or p.title or '').split(' - OutilGraphique')[0].strip()
    desc = m.get('og:description') or m.get('description') or ''
    img = m.get('og:image') or ''
    # date affichée sur la fiche, ex. « oct. 2026 » (indicative)
    shown = ''
    for t in p.text:
        mm = re.fullmatch(r'([a-zéû]+)\.?\s+(20\d\d)', t.lower())
        if mm and mm.group(1)[:4].rstrip('.') in {k[:4] for k in MOIS}:
            shown = t
            break
    return {'url': url, 'name': name or url.rsplit('/', 1)[-1], 'desc': desc, 'image': img, 'shown_date': shown}


def sitemap_urls():
    xml = get(SITE + '/sitemap.xml')
    urls = [html.unescape(u) for u in re.findall(r'<loc>\s*([^<]+?)\s*</loc>', xml)]
    return sorted({u for u in urls if SECTION in u and u.rstrip('/').rsplit('/', 1)[-1] and not u.endswith(SECTION)})


def slug(url):
    return urllib.parse.unquote(url.rstrip('/').rsplit('/', 1)[-1])


def outils_accueil():
    """Fiches affichées dans la liste « Outil » de l'accueil (mode par défaut)."""
    page = get(SITE + '/')
    return {urllib.parse.unquote(m) for m in re.findall(r'href="\./outil/([^"?#]+)"', page)}


def write_feed(items):
    now = format_datetime(datetime.now(timezone.utc))
    out = ['<?xml version="1.0" encoding="UTF-8"?>',
           '<rss version="2.0" xmlns:media="http://search.yahoo.com/mrss/" xmlns:atom="http://www.w3.org/2005/Atom">',
           '<channel>',
           '<title>OutilGraphique</title>',
           f'<link>{escape(SITE)}</link>',
           '<description>Les projets graphiques repérés par OutilGraphique.</description>',
           '<language>fr</language>',
           f'<lastBuildDate>{now}</lastBuildDate>']
    for it in items[:MAX_ITEMS]:
        pub = format_datetime(datetime.fromisoformat(it['first_seen']))
        img = it.get('image') or ''
        desc_html = (f'<p><img src="{html.escape(img)}" alt="{html.escape(it["name"])}"></p>' if img else '') + f'<p>{html.escape(it.get("desc") or "")}</p>'
        out += ['<item>',
                f'<title>{escape(it["name"])}</title>',
                f'<link>{escape(it["url"])}</link>',
                f'<guid isPermaLink="true">{escape(it["url"])}</guid>',
                f'<pubDate>{pub}</pubDate>',
                f'<description>{escape(desc_html)}</description>']
        if img:
            out += [f'<media:content url="{escape(img)}" medium="image"/>',
                    f'<enclosure url="{escape(img)}" type="image/jpeg" length="0"/>']
        out.append('</item>')
    out += ['</channel>', '</rss>', '']
    open(FEED, 'w', encoding='utf-8').write('\n'.join(out))


def announce_discord(it):
    hook = os.environ.get('DISCORD_WEBHOOK', '').strip()
    if not hook:
        return
    embed = {'title': it['name'], 'url': it['url'], 'description': it.get('desc') or '', 'color': 0x000000}
    if it.get('image'):
        embed['image'] = {'url': it['image']}
    post_json(hook, {'username': 'OutilGraphique', 'content': 'Nouveau projet graphique sur OutilGraphique', 'embeds': [embed]})


def add_arena(it):
    token, channel = os.environ.get('ARENA_TOKEN', '').strip(), os.environ.get('ARENA_CHANNEL', '').strip()
    if not (token and channel):
        return
    post_json(f'https://api.are.na/v2/channels/{channel}/blocks', {'source': it['url']}, {'Authorization': 'Bearer ' + token})


def main():
    state = json.load(open(STATE)) if os.path.exists(STATE) else {'items': []}
    first_run = not state['items']
    known = {it['url'] for it in state['items']}
    new = [u for u in sitemap_urls() if u not in known]
    outils = OUTILS_CONNUS | outils_accueil() | {slug(it['url']) for it in state['items'] if it.get('type') == 'outil'}
    for it in state['items']:
        it['type'] = 'outil' if slug(it['url']) in outils else 'graphique'
    print(f'{len(known)} fiches connues, {len(new)} nouvelle(s).')
    errors = 0
    for u in new:
        try:
            it = read_tool(u)
        except Exception as e:  # une fiche illisible ne bloque pas les autres
            print('Fiche illisible :', u, e)
            errors += 1
            continue
        it['first_seen'] = datetime.now(timezone.utc).isoformat(timespec='seconds')
        it['type'] = 'outil' if slug(u) in outils else 'graphique'
        state['items'].insert(0, it)
        if first_run:
            continue
        if it['type'] == 'outil':
            print('Nouvel outil, pas partagé :', it['name'])
            continue
        print('Nouveau projet graphique :', it['name'])
        for f, label in ((announce_discord, 'Discord'), (add_arena, 'Are.na')):
            try:
                f(it)
            except urllib.error.HTTPError as e:
                print(f'{label} a refusé : {e.code} {e.read()[:200]!r}')
                errors += 1
            except Exception as e:
                print(f'{label} injoignable : {e}')
                errors += 1
    # Bouton « Run workflow » avec test coché : réannonce le dernier projet graphique pour vérifier Discord et Are.na
    graphiques = [it for it in state['items'] if it.get('type') == 'graphique']
    if os.environ.get('TEST_ANNOUNCE') == 'true' and graphiques:
        it = graphiques[0]
        print('Test : annonce de', it['name'])
        announce_discord(it)
        add_arena(it)
    json.dump(state, open(STATE, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    write_feed(graphiques)
    print(f'Flux : {len(graphiques)} projets graphiques ({len(state["items"]) - len(graphiques)} outils mis de côté).')
    if first_run:
        print(f'Premier passage : {len(state["items"])} fiches notées, rien annoncé.')
    return 1 if errors and not new else 0


if __name__ == '__main__':
    sys.exit(main())
