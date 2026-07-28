# Instagram Audio API

The Instagram Audio API allows you to retrieve and search for audio — both original sounds from Instagram Reels and music — and attach them to Reels at creation time. This API is available on the Instagram Platform with Facebook Login.

## Before You Start

You need the following:

* An Instagram Business or Instagram Creator account
* A Facebook Page connected to that account
* A registered Facebook App with the following permissions granted via Facebook Login:
  + `instagram_basic`
  + `instagram_content_publish`
* A valid User access token

### Limitations

* Music availability: This API returns audio that has been authorized for third party use. Note that the available selection may vary from what appears in the native app.
* Platform support: This API is only available on the Instagram API with Facebook Login. It is not supported on the Instagram API with Instagram Login.
* Reel previews: Previewing a Reel with attached audio is not supported. The Reel will be published as configured.
* Filter constraints: When retrieving audio, if no search query is provided, trending audio is returned.

## Endpoints

### Search audio assets

Search for audio assets to use in Reels. You can search for original sounds from existing Reels or music. If a search query is omitted, trending original sounds or music are returned by default.

#### Request syntax

```
GET /ig_audio?audio_type={audio-type}&user_id={user-id}&access_token={access-token}
```

#### Query string parameters

Parameter | Type | Description || `audio_type` | Enum | Required. The type of audio to search for. Values: `original_sound`, `music`. |
| `user_id` | String | Required. The ID of the Instagram User performing the query. |
| `search_query` | String | Optional. A search string to filter results by keyword. |
| `access_token` | String | Required. A valid User access token. |

#### Sample request

```
curl -X GET "https://graph.facebook.com/v22.0/ig_audio?audio_type=music&user_id={user-id}&access_token={access-token}"
```

#### Sample response

```
{
  "audio": [
    {
      "audio_id": "587784541076604",
      "cover_artwork_thumbnail_uri": "https://scontent-...",
      "display_artist": "Shuba",
      "duration_in_ms": 153760,
      "audio_type": "music",
      "title": "Birthday Wish",
      "download_url": "https://scontent-lga3..."
    },
    {
      "audio_id": "587784541076614",
      "display_artist": "Drake",
      "duration_in_ms": 153760,
      "audio_type": "music",
      "title": "Birthday Wish",
      "on_platform_audio_preview_link": "https://www.instagram.com...",
      "is_ads_eligible": false
    }
  ]
}
```

#### Response fields

Field | Type | Description || `audio_id` | String | The unique identifier for the audio asset. |
| `cover_artwork_thumbnail_uri` | String | URL of the cover artwork thumbnail. Returned for music type only. May be null when no URL is available. |
| `display_artist` | String | The display name of the artist. Returned for music type only. |
| `duration_in_ms` | Integer | Duration of the audio asset in milliseconds. |
| `audio_type` | Integer | Type of the audio asset. |
| `title` | String | Title of the audio asset. |
| `download_url` | String | A temporary URL to preview the audio file. This URL expires after approximately 1.5 days. May be null when no preview URL is available. |
| `ig_username` | String | The Instagram username of the creator. Returned for `original_sound` type only. |
| `profile_picture_url` | String | URL of the creator's profile picture. Returned for `original_sound` type only. |
| `is_ads_eligible` | Boolean | Nullable boolean which shows if the audio asset can be used in ads. |
| `on_platform_audio_preview_link` | String | URL to preview the audio. May be null when not available. |

### Get audio metadata

Retrieve metadata for a specific audio asset by its ID.

#### Request syntax

```
GET /{ig-audio-id}?user_id={user-id}&access_token={access-token}
```

#### Path parameters

Parameter | Type | Description || `{ig-audio-id}` | String | Required. The unique identifier (FBID) of the audio asset. |

#### Query string parameters

Parameter | Type | Description || `user_id` | String | Required. The ID of the Instagram User performing the query. |
| `access_token` | String | Required. A valid User access token. |

#### Sample request

```
curl -X GET "https://graph.facebook.com/v22.0/587784541076604?user_id={user-id}&access_token={access-token}"
```

### Sample response

```
{
  "audio_id": "587784541076604",
  "cover_artwork_thumbnail_url": "https://scontent-lga3-...",
  "display_artist": "Shuba",
  "duration_in_ms": 153760,
  "audio_type": "music",
  "title": "Birthday Wish",
  "download_url": "https://scontent-lga3..."
}
```

### Response fields

Field | Type | Description || `audio_id` | String | The unique identifier for the audio asset. |
| `cover_artwork_thumbnail_url` | String | URL of the cover artwork thumbnail. Returned for music type only. May be null when no URL is available. |
| `display_artist` | String | The display name of the artist. Returned for music type only. |
| `duration_in_ms` | Integer | Duration of the audio track in milliseconds. |
| `audio_type` | String | The type of audio: music or original\_sound. |
| `title` | String | The title of the audio track. |
| `download_url` | String | A temporary URL to preview the audio file. This URL expires after approximately 1.5 days. May be null when no preview URL is available. |
| `ig_username` | String | The Instagram username of the original audio creator. Returned for `original_sound` type only. |
| `profile_picture_url` | String | URL of the creator's profile picture. Returned for `original_sound` type only. |
| `is_ads_eligible` | Boolean | Nullable boolean which shows if the audio asset can be used in ads. |
| `on_platform_audio_preview_link` | String | URL to preview the audio. May be null when not available. |

### Discover replacement audio for ads

Discover royalty-free Sound Collection tracks to replace copyrighted music in an Instagram Reel before promoting it as an ad. This uses the same `/ig_audio` endpoint with `product=ADS`.

**Performing the swap:** This endpoint only discovers replacement audio. To apply a discovered track to an Instagram Reels ad, see [IG Audio Swap for Instagram Reels Ads](/documentation/ads-commerce/marketing-api/out-of-cycle-changes/occ-2026#ig-audio-swap-for-instagram-reels-ads).

**Required permission:** `ads_management`.

**Availability:** This feature is in limited release. Requests from apps without access return a `200`-level permission error.

#### Request syntax

```
GET /ig_audio?product=ADS&purpose=AUDIO_COPYRIGHT_REPLACEMENT&audio_replacement_mode={mode}&ig_media_id={ig-media-id}&access_token={access-token}
```

**Note:** `ig_media_id` is required for every mode and must reference a Reel that contains copyrighted music. Photos, carousels, and Reels without a copyright issue are rejected.

#### Query string parameters

Parameter | Type | Description || `product` | Enum | Required. Set to `ADS` to use ads audio features. |
| `purpose` | Enum | Required. Set to `AUDIO_COPYRIGHT_REPLACEMENT`, currently the only supported sub-use case for `product=ADS`. |
| `audio_replacement_mode` | Enum | Required. How audio is discovered. `default` returns the popularity-ranked Sound Collection list shown in Meta Ads Manager. `search` performs a text search across the Sound Collection (requires `search_query`). `auto` returns the single best-match track recommended for the Reel referenced by `ig_media_id`. |
| `ig_media_id` | String | Required for all modes. The FBID (from `/me/media`) of the IG Reel containing the copyrighted music to replace. The media must be a Reel with a detected copyright issue. In `auto` mode it drives the recommendation; in `search` and `default` modes it is required context but does not affect ranking. |
| `search_query` | String | Required when `audio_replacement_mode=search`; not allowed in `auto` or `default` modes. A keyword string matched against song title, artist, and the search index. |
| `ig_user_id` | String | **Required for partnership ad media.** Also required for agency or multi-account tokens. Optional otherwise for `product=ADS` — the `ads_management` grant authorizes the call and the IG account is derived from the access token. |
| `partnership_ad_code` | String | Optional. For partnership ads, the ad code authorizing access to the creator's media. Must correspond to the same media as `ig_media_id`. |
| `access_token` | String | Required. A valid User access token with `ads_management`. |

Results are returned in pages. `default` returns up to 30 tracks, `search` up to 25 per page, and `auto` returns a single track.

#### Sample request

```
curl -X GET "https://graph.facebook.com/v22.0/ig_audio?product=ADS&purpose=AUDIO_COPYRIGHT_REPLACEMENT&audio_replacement_mode=default&ig_media_id={ig-media-id}&access_token={access-token}"
```

#### Sample response

```
{
  "audio": [
    {
      "audio_id": "587784541076604",
      "cover_artwork_thumbnail_uri": "https://scontent-...",
      "display_artist": "Shuba",
      "duration_in_ms": 153760,
      "title": "Birthday Wish",
      "download_url": "https://scontent-lga3..."
    }
  ]
}
```

#### Response fields

Ads responses return royalty-free music only and include the following fields:

Field | Type | Description || `audio_id` | String | The unique identifier for the audio asset. Use this value as the `audio_id` in `audio_configuration` when publishing the Reel. |
| `cover_artwork_thumbnail_uri` | String | URL of the cover artwork thumbnail. |
| `display_artist` | String | The display name of the artist. |
| `duration_in_ms` | Integer | Duration of the track in milliseconds. |
| `title` | String | The title of the track. |
| `download_url` | String | A temporary URL to preview the audio file. May be empty when no preview URL is available. |

#### Errors

See the [Error Codes reference](/docs/instagram-platform/instagram-graph-api/reference/error-codes) for error responses.

### Publish a Reel with audio

Attach an audio asset to a Reel during content creation. This uses the existing Content Publishing flow with an additional `audio_configuration` parameter.

#### Step 1: Create a media container

#### Request syntax

```
POST /{ig-user-id}/media
```

Include the new `audio_configuration` object alongside your existing Reel parameters (`video_url`, `media_type=REELS`, etc.).

**Note:** New parameter: `audio_configuration`

Field | Type | Description || `audio_id` | String | Required. The unique identifier of the audio asset to attach, obtained from the Search Audio or Get Audio Metadata endpoints. |
| `audio_volume` | Integer | Optional. Volume level for the audio asset, from 0 (muted) to 100 (full volume). Defaults to 100. |
| `video_volume` | Integer | Optional. Volume level for the video's original audio, from 0 (muted) to 100 (full volume). Defaults to 100. |

#### Sample request

```
curl -X POST "https://graph.facebook.com/v22.0/{ig-user-id}/media" \
  -d "media_type=REELS" \
  -d "video_url={video-url}" \
  -d 'audio_configuration={"audio_id":"587784541076604","audio_volume":80,"video_volume":50}' \
  -d "access_token={access-token}"
```

#### Step 2: Publish the media container

Once the container is created, publish it using the standard publishing endpoint:

```
POST /{ig-user-id}/media_publish?creation_id={creation-id}access_token={access-token}
```

Refer to the Content Publishing documentation for full details on the two-step publishing flow.

Example workflow

Here is a complete example showing how to search for trending music and attach it to a Reel:

1. Search for trending music:

```
curl -X GET "https://graph.facebook.com/v22.0/ig_audio?audio_type=musicuser_id={user-id}access_token={access-token}"
```

1. (Optional) Get metadata for a specific audio asset:

```
curl -X GET "https://graph.facebook.com/v22.0/{audio-id}?user_id={user-id}access_token={access-token}"
```

1. Create a Reel container with the audio attached:

```
curl -X POST "https://graph.facebook.com/v22.0/{ig-user-id}/media" \
  -d "media_type=REELS" \
  -d "video_url={video-url}" \
  -d 'audio_configuration={"audio_id":"{audio-id}","audio_volume":100,"video_volume":60,"should_loop_audio":false}' \
  -d "access_token={access-token}"
```

1. Publish the Reel:

```
curl -X POST "https://graph.facebook.com/v22.0/{ig-user-id}/media_publish?creation_id={creation-id}access_token={access-token}"
```
