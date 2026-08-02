# AIOStreams Kodi Plugin Documentation

## Contents

- [Overview](#overview)
- [Required Configuration](#required-configuration)
- [Custom Formatter Option](#custom-formatter-option)
- [Installation](#installation)
- [Quick Start Guide](#quick-start-guide)
- [Troubleshooting](#troubleshooting)

## Overview

**AIOStreams for KODI** is a powerful Kodi video plugin that connects to your self-hosted AIOStreams backend, providing seamless access to streaming content with advanced features like Trakt synchronization, intelligent stream selection, and comprehensive metadata integration.

### What Does AIOStreams for KODI Do?

AIOStreams acts as a frontend client for your [AIOStreams backend](https://github.com/Viren070/aiostreams), bringing powerful streaming aggregation directly into your Kodi media center:

- **🎬 Content Discovery**: Browse catalogs, search movies/TV shows, and discover trending content
- **📺 Trakt Integration**: Full sync with watchlist, collections, watch history, and Next Up
- **🎯 Smart Stream Selection**: Automatic quality filtering, reliability tracking, and preference learning
- **⏭️ Autoplay Next Episode**: Configurable auto-play with background stream pre-loading
- **🎨 Rich Metadata**: TMDb/TVDb integration with posters, fanart, cast information, and ratings
- **🌐 Subtitle Support**: Automatic subtitle scraping via AIOStreams backend
- **🎥 Trailer Playback**: YouTube trailer integration for content preview
- **🔎 Recent Searches**: Search All, Movies, and Series separately; up to 20 recent query-and-scope pairs can be rerun, removed individually, or cleared.
- **⭐ Native Favorites**: Browse your Kodi Favorites that belong to AIOStreams and manage them with Kodi’s standard favorite controls.

---

## Required Configuration

### 1. AIOStreams Backend

You **must** have a running AIOStreams instance configured with:

#### Required Components:
- **Metadata Provider**: Should provide stable IMDb IDs; TMDb IDs are also supported when reopening a favorite under a different configuration.
- **Recommended metadata provider**: [AIOMetadata](https://github.com/cedya77/aiometadata) provides rich metadata, catalog support, and IMDb ID integration.
- **Search Provider**: Configure at least one search provider; AIOMetadata provides unified search across content types.
- **Scraper**: At least one torrent indexer or debrid service configured

#### Backend Setup:
1. Deploy AIOStreams (self-hosted or via ElfHosted)
2. Configure AIOMetadata as your metadata provider
3. Set up scrapers (torrent indexers, debrid services)
4. Ensure IMDB tags are enabled in metadata responses

### 2. Plugin Settings

Access settings via: **Add-ons → Video add-ons → AIOStreams → Right-click → Settings**

#### Essential Settings:

**General**
- **AIOStreams Host URL**: Your backend URL (e.g., `https://aiostreams.elfhosted.com`)
- **API Timeout**: How long the add-on waits for a backend response

**Playback**
- **Preferred Quality**: Set your preferred stream quality (4K, 1080p, 720p, etc.)
- **Minimum Quality**: Lowest acceptable quality (filters out lower quality streams)
- **Auto-play**: Enable automatic stream selection based on preferences

**Trakt Integration** (Optional)
- **Enable Trakt**: Authorize your Trakt account for sync features
- **Auto-Sync**: Automatic synchronization of watch history and progress
- **Auto-Sync**: Keeps watch history and progress synchronized in the background

---

## Custom Formatter Option

AIOStreams supports **custom stream title formatting** to display stream information exactly how you want it.

### Enabling Custom Formatting

1. Go to: **Settings → Playback → Stream Display**
2. Enable **"Use Custom Formatter"**
3. Enter your custom format string

### Format Specification

Use the following custom formatter parameters in your format string, all in the 'Name' section, leave Description empty:

```
{stream.resolution::exists["RESOLUTION: {stream.resolution}"||""]}
{service.name::exists["SERVICE: {service.name}"||""]}
{addon.name::exists["ADDON: {addon.name}"||""]}
{stream.size::>0["SIZE: {stream.size::bytes}"||""]}
{stream.proxied::istrue["PROXIED: YES"||""]}{stream.proxied::isfalse["PROXIED: NO"||""]}
{service.cached::istrue["CACHED: YES"||""]}{service.cached::isfalse["CACHED:NO"||""]}
{stream.library::istrue["IN LIBRARY: YES"||""]}{stream.library::isfalse["IN LIBRARY: NO"||""]}
{stream.duration::>0["DURATION: {stream.duration::time} "||""]}
{stream.quality::exists["VIDEO: {stream.quality}"||""]} | {stream.visualTags} | {stream.encode}
{stream.audioTags::exists["AUDIO: {stream.audioTags::join(' | ')} | {stream.audioChannels}"||""]}{stream.languages::exists[" | {stream.languages::join(' / ')}"||""]}
{stream.indexer::exists["INDEXER: {stream.indexer} "||""]}{stream.seeders::exists["| {stream.seeders} Seeders"||""]}{stream.age::exists[" | {stream.age} Old"||""]}
{stream.filename::exists["FILENAME: {stream.filename}"||""]}
```


---

## Installation

1. In Kodi, open **Settings → File manager → Add source**, enter `https://voidxela.github.io/AIOStreamsKODI/`, and give it a memorable name such as **AIOStreams**.
2. Open **Settings → Add-ons → Install from zip file**, select the **AIOStreams** source, then select [{{REPOSITORY_ZIP}}]({{REPOSITORY_ZIP}}). The same link can be downloaded in a browser when needed.
3. Confirm the repository installation.
4. Open **Settings → Add-ons → Install from repository → AIOStreams Repository → Video add-ons → AIOStreams**, then select **Install**.

---

## Quick Start Guide

1. **Install the plugin** (see Installation above)
2. **Configure AIOStreams backend** with AIOMetadata
3. **Open plugin settings** and enter your backend URL
4. **(Optional) Authorize Trakt** for sync features
5. **Browse catalogs** or search for content
6. **Select a stream** and enjoy!

---

## Troubleshooting

### No Streams Found
- Verify your AIOStreams backend is running and accessible
- Check that scrapers are configured in your backend
- Ensure metadata provider (AIOMetadata) is properly configured

### External ID Errors
- Confirm your metadata provider serves stable IMDb or TMDb IDs
- AIOMetadata is recommended for reliable external ID support
- Check backend logs for metadata provider errors

### Trakt Sync Issues
- Re-authorize Trakt in plugin settings
- Check Trakt API status at [trakt.tv/status](https://trakt.tv/status)
- Verify automatic sync is enabled and allow it to complete before retrying

---

**License**: MIT
