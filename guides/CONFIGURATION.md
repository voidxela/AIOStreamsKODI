# AIOStreams Configuration

This page provides guidance on configuring your AIOStreams environment for the best experience with the Kodi plugin and skin.

## Table of Contents
- [Recommended Backend Setup](#recommended-backend-setup)
- [Tam-Taro's SEL Lists](#tam-taros-sel-lists)
- [Embedding AIOStreams](#embedding-aiostreams)
- [Custom Formatter Configuration](#custom-formatter-configuration)
- [Important Credentials](#important-credentials)

---

## Recommended Backend Setup

For the most stable and feature-rich experience, it is highly recommended to follow **Tam-Taro's guide** for setting up both **AIOStreams** and **AIOMetadata**.

- **AIOStreams**: The core backend that aggregates your streams.
- **AIOMetadata**: Provides rich metadata, catalogs, and unified search.

Ensure both are correctly installed and communicating with each other.

## Tam-Taro's SEL Lists

I suggest using **Tam-Taro's SEL (Stream Entry Lists)**. These lists are curated to ensure high-quality stream availability and better organization of content. Integrating these into your backend setup significantly improves the discovery process within Kodi.

## Embedding AIOStreams

To serve metadata and catalogs efficiently, you should **embed the AIOStreams instance into AIOStreams**. This allows the backend to act as its own provider for catalogs, ensuring that the Kodi plugin can access all content directly from your hosted instance without relying on external metadata latency for primary navigation.

## Custom Formatter Configuration

AIOStreams allows for highly detailed stream information display. We recommend using the following template for the **Custom Formatter Name**. 

> [!IMPORTANT]
> Leave the **Description Template** blank and place all the logic into the **Name Template**.

### Name Template
```text
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

## Important Credentials

Keep a secure note of your specific AIOStreams instance details to ensure seamless connection from the Kodi plugin.

- **AIOStreams Host**: `[Your Host URL]`
- **UUID**: `[Your Instance UUID]`
- **Password**: `[Your Instance Password]`

## History

New profiles use **Local History**, stored in the add-on profile's `user_state.db`.
It tracks watched state, resume points, and Next Up without sending playback
events to a third party. Select **Disabled** in *History* to turn
off history UI and writes entirely.

Each provider has a **Configure History Provider** wizard and publishes its
own read-only status details on this page. Local History shows its database
path and tracking metrics. The legacy Trakt wizard owns the user-supplied
client credentials and authorization flow.

Existing profiles that already have a valid user-configured Trakt token are
migrated once to the **legacy Trakt history** compatibility provider. The
separate Trakt watchlist integration remains available regardless of the
selected history provider. Use *Import Cached Trakt History into Local History*
only when you explicitly want to copy stable watched/resume cache data; it does
not copy collections, ratings, or watchlists.

---

## Troubleshooting Manifest Updates

If you make changes to your AIOStreams manifest (e.g., adding or removing lists) and they don't appear in Kodi immediately:

1.  **Refresh Manifest**: Go to **Add-on Settings > Advanced > Maintenance** and select **Refresh Manifest Cache**.
2.  **Restart Kodi**: A full restart will often clear persistent plugin caches.
