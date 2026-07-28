# Error Codes



This document describes the error messages that can be returned by the Instragram API. The sample response below shows an example of code `3600` and subcode `2207004` with the subsequent error codes defined.

### Sample Response

```json
&#123;
  &quot;error&quot;:
    &#123;
      &quot;message&quot;: &quot;The image size is too large.&quot;,
      &quot;type&quot;: &quot;OAuthException&quot;,
      &quot;code&quot;: 36000,
      &quot;error_subcode&quot;: 2207004,
      &quot;is_transient&quot;: false,
      &quot;error_user_title&quot;: &quot;Image size too large&quot;,
      &quot;error_user_msg&quot;: &quot;The image is too large to download. It should be less than 8 MiB.&quot;,
      &quot;fbtrace_id&quot;: &quot;A6LJylpZRKw2xKLFsAP-cJh&quot;
   &#125;
 &#125;
```

### Error Codes Defined

| HTTP Status Code | Code | Subcode | User Message | Recommended Solution |
| --- | --- | --- | --- | --- |
| `400` | `-2` | `2207003` | `It takes too long to download the media.` | A timeout occured while downloading the media. Try again. |
| `400` | `-2` | `2207020` | `The media you are trying to access has expired. Please try to upload again.` | Generate a new container ID and use it to try again. |
| `400` | `-1` | `2207001` |  | Instagram server error. Try again. |
| `400` | `-1` | `2207032` | `Create media fail, please try to re-create media` | Failed to create a media container. Try again. |
| `400` | `-1` | `2207053` | `unknown upload error` | An unknown error occured during upload. Generate a new container and use it to try again. This should only affect video uploads. |
| `400` | `1` | `2207057` | `Thumbnail offset must be greater than or equal to 0 and less than video duration, i.e.` &#123;video-length&#125; | The thumbnail offset you entered is out of bounds for the video duration. Add the right offset in milliseconds. |
| `400` | `4` | `2207051` | `We restrict certain activity to protect our community. Tell us if you think we made a mistake.` | The publishing action is suspected to be spam. We restrict certain activity to protect our community. Let us know if you can determine that the publishing actions is not spam. |
| `400` | `9` | `2207042` | `You reached maximum number of posts that is allowed to be published by Content Publishing API.` | The app user has reached their daily publishing limit. Advise the app&#039;s user to try again the following day. |
| `400` | `24` | `2207006` | `The media with` &#123;media-id&#125; `cannot be found` | Possible permission error due to missing permission or expired token. Generate a new container and use it to try again. |
| `400` | `24` | `2207008` | `The media builder with creation id =` &#123;creation-id&#125; `does not exist or has been expired.` | Temporary error publishing a container. Try again 1–2 times in the next 30 seconds to 2 minutes. If unsuccessful, generate a new container ID and use it to try again. |
| `400` | `25` | `2207050` | `The Instagram account is restricted.` | The app user&#039;s Instagram Professional account is inactive, checkpointed, or restricted. Advise the app user to sign in to the Instagram app and complete any actions the app requires to re-enable their account. |
| `400` | `100` | `2207023` | `The media type` &#123;media-type&#125; `is unknown.` | The media type entered is not one of the [expected media types](https://developers.facebook.com/documentation/instagram-platform/reference/instagram-media#fields). Please enter the correct one. |
| `400` | `100` | `2207028` | `Your post won&#039;t work as a carousel. Carousels need at least 2 photos/videos and no more than 10 photos/videos.` | Try again using an acceptable number of photos/videos. |
| `400` | `100` | `2207035` | `Product tag positions should not be specified for video media.` | Videos do not support X/Y coordinates. Disallow X/Y coordinates with videos. |
| `400` | `100` | `2207036` | `Product tag positions are required for photo media.` | Image product tags must include X/Y coordinates. Require X/Y coordinates for images. |
| `400` | `100` | `2207037` | `We couldn&#039;t add all of your product tags. The product ID may be incorrect, the product may be deleted, or you may not have permission to tag the product.` | One or more of the products being used to tag the item is invalid (deleted, rejected, app user lacks permission, product ID is invalid, etc.). Get the app user&#039;s catalogs and eligible products again and allow the app user to only use those product IDs when tagging. |
| `400` | `100` | `2207040` | `Cannot use more than` &#123;max-tag-count&#125; `tags per created media.` | The app user exceeded the maximum number (20) of &#064; tags. Advise user to use fewer &#064; tags. |
| `400` | `352` | `2207026` | `The video format is not supported. Please check spec for supported` &#123;video&#125; `format` | Unsupported video format. Advise the app user to upload an MOV or MP4 (MPEG-4 Part 14). See [Video Specifications](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-user/media#video-specifications). |
| `400` | `9004` | `2207052` | `The media could not be fetched from this uri:` &#123;uri&#125; | The media could not be fetched from the supplied URI. Advise the app user to make sure the URI is valid and publicly available. |
| `400` | `9007` | `2207027` | `The media is not ready for publishing, please wait for a moment` | [Check the container status](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-container#fields) and publish when its status is `FINISHED`. |
| `400` | `36000` | `2207004` | `The image is too large to download. It should be less than` &#123;size&#125;`.` | Image exceeded maximum file size of 8MiB. Advise the user to try again with a smaller image. |
| `400` | `36001` | `2207005` | `The image format` &#123;current-image-format&#125; `is not supported. Supported formats are:` &#123;format&#125;`.` | Possible permission error due to missing permission or expired token. Generate a new container and use it to try again. |
| `400` | `36003` | `2207009` | `The submitted image with aspect ratio` &#123;submitted-ratio&#125; `cannot be published. Please submit an image with a valid aspect ratio.` | The image&#039;s aspect ratio does not fall within our acceptable range. Advise the app user to try again with an image that falls withing a 4:5 to 1.91:1 range. |
| `400` | `36004` | `2207010` | `The submitted image&#039;s caption was` &#123;submitted-caption-length&#125; `characters long. The maximum number of characters permitted for a caption is` &#123;maximum-caption-length&#125;. `Please submit media with a shorter caption.` | The user exceeded the maximum amount of characters for a caption. Advise user to use a shorter caption. Maximum 2,200 characters, 30 hashtags, and 20 &#064; tags. |
| `400` | `100` | `9050` | `Provide either user_id or ig_user_id, not both.` | `/ig_audio` received both `user_id` and `ig_user_id`. Send only one; prefer `ig_user_id`. |
| `400` | `100` | `9052` | `Missing or invalid purpose for product=ADS.` | Set `purpose=AUDIO_COPYRIGHT_REPLACEMENT`, currently the only supported sub-use case for `product=ADS`. |
| `400` | `100` | `9056` | `Missing required parameter audio_replacement_mode.` | Send `audio_replacement_mode` as one of `auto`, `search`, or `default`. |
| `400` | `100` | `9057` | `Invalid audio_replacement_mode value.` | Use one of `auto`, `search`, or `default` (case-insensitive). |
| `400` | `100` | `9058` | `Missing required parameter search_query.` | `search_query` is required when `audio_replacement_mode=search`. Append a search term. |
| `400` | `100` | `9060` | `The search_query parameter is only valid when audio_replacement_mode=search.` | Drop `search_query` in `auto`/`default` modes, or set `audio_replacement_mode=search`. |
| `400` | `100` | `9054` | `The ig_media_id parameter is required.` | Provide the IG media FBID (from `/me/media`) of the Reel whose copyrighted music needs replacing. |
| `400` | `100` | `9062` | `The supplied ig_media_id refers to a non-Reel media.` | Audio swap discovery supports Reels only. Provide the FBID of a Reel. |
| `400` | `100` | `9055` | `This media does not contain copyrighted licensed music.` | Audio swap discovery is only available for Reels with copyrighted music. Choose a Reel with a copyright issue. |
| `400` | `100` | `9063` | `The supplied partnership_ad_code is invalid or expired.` | Generate a valid partnership ad code and retry. |
| `400` | `100` | `9064` | `The supplied partnership_ad_code does not match the ig_media_id.` | Use a `partnership_ad_code` generated for the same media as `ig_media_id`. |
| `403` | `200` |  | `The calling app is missing the ads_management permission for the target.` | Request and obtain the `ads_management` permission for the target user, then retry. |
| `403` | `10` | `9053` | `Ads audio swap discovery is not yet available.` | This feature is in limited release. Access is gated; reach out to your Meta partner contact. |

