# Simple Web Crawler (PyQt6 GUI)

A desktop GUI application for crawling websites, mapping their structure, detecting endpoints that accept parameters, and exporting results to CSV/JSON. It optionally visualizes the site graph using NetworkX and Matplotlib.

Built with **Python 3**, **PyQt6**, **Requests**, and **BeautifulSoup4**.

---

## Features

- Crawl any website with configurable depth and page limit
- Restrict crawling to the same domain
- Detect URLs and forms that accept parameters
- Track HTTP status codes and out-degree (links to other pages)
- Display results in a rich **table GUI**
- Export results to **CSV** or **JSON**
- Optional site graph visualization (requires `networkx` and `matplotlib`)
- Supports delays between requests to avoid overloading servers

---

## Screenshots

![ScreenShot](images/ScreenShot.png)

---

## System Requirements

**Minimum:**
- Windows 10 / 11 64-bit
- CPU: Quad-core or better
- RAM: 8 GB
- Disk space: 4 GB free (EXE occupy ~3 GB)
- Python 3.10+ installed (if running from source)

**Recommended for EXE deployment:**
- CPU: 6+ cores
- RAM: 16 GB+
- SSD for faster crawling and saving large datasets
- Network access for crawling external sites

**Python libraries (if running from source):**
```bash
pip install pyqt6 requests beautifulsoup4 networkx matplotlib
⚠️ The standalone EXE build (PyInstaller) is large (~3 GB) because it bundles Python runtime, PyQt6, Matplotlib, and all dependencies.

Installation
From source
Clone the repo:

bash

git clone https://github.com/Luka12-dev/Simple-Web-Crawler.git
cd Simple-Web-Crawler
Install dependencies:

bash

python crawler_gui.py
Standalone EXE
Navigate to the dist folder after building with PyInstaller.

Double-click SimpleWebCrawler.exe to launch.

Make sure you have at least 3 GB free RAM and disk space.

Usage
Enter the starting URL

Set max pages, max depth, and other options

Click Start Crawl

Monitor progress in the log area

Export results via CSV/JSON or visualize the graph

Notes
Crawling external websites can be slow depending on server response

Use the delay option to avoid rate-limiting or IP bans

Optional graph visualization requires networkx + matplotlib

EXE builds are large due to PyQt6 + Matplotlib + bundled Python

License
MIT License - free to use, modify, and distribute