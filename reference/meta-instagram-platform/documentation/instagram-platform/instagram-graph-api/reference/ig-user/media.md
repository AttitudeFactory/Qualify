# IG User Media



Represents a collection of [IG Media](https://developers.facebook.com/documentation/instagram-platform/reference/instagram-media) objects on an [IG User](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-user).

**Success:** On July 9, 2025, we added support for the existing `user_tags` field for image and video stories on the `/&lt;IG_ID&gt;/media` endpoint. You can mention users in a story and optionally specify x, y coordinates to tag them at a particular coordinate in the media.

## Creating

**`POST /&lt;YOUR_APP_USERS_INSTAGRAM_USER_ID&gt;/media`**

* Create an image, carousel, story or reel [IG Container](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-container) for use in the post publishing process. See the [Content Publishing](https://developers.facebook.com/documentation/instagram-platform/content-publishing) guide for complete publishing steps.

Steps to publish a media object include the following:

1. Create a container
2. Upload the media to the container
3. Publish the container

### Limitations &#123;#limitations&#125;

#### General Limitations &#123;#limitations-general&#125;

* Containers expire after 24 hours
* An Instagram account can only create 400 containers within a rolling 24 hour period
* If the [Page](https://developers.facebook.com/documentation/instagram-platform/overview#pages) connected to the targeted Instagram professional account requires [Page Publishing Authorization](https://www.facebook.com/help/www/1939753742723975) (PPA), PPA must be completed or the request will fail
* If the Page connected to the targeted Instagram professional account requires two-factor authentication, the Facebook User must also have performed two-factor authentication or the request will fail
* We strongly recommended the HTTP IETF standard character set for URLs, URLs that contain only US ASCII characters, or the request will fail

#### Reels Limitations &#123;#limitations-reels&#125;

* Reels cannot appear in carousels
* Account privacy settings are respected upon publish. For example, if **Allow remixing** is enabled, published reels will have remixing enabled upon publish but remixing can be disabled on published reels manually through the Instagram app.
* Music tagging is only available for original audio.

#### Story Limitations

* Stories expire after 24 hours.
* Support either video URL or Reels URL but not both.
* Publishing stickers (i.e., link, poll, location) is not supported; however    mentioning users without a sticker is supported.  

### Requirements

| Type | Description |
| --- | --- |
| [Access Tokens](https://developers.facebook.com/documentation/facebook-login/guides/access-tokens#usertokens) | [User](https://developers.facebook.com/documentation/facebook-login/guides/access-tokens#usertokens) |
| [Business Roles](https://www.facebook.com/business/help/442345745885606) | If creating containers for [product tagging](https://developers.facebook.com/documentation/instagram-platform/instagram-api-with-facebook-login/product-tagging), the app user must have an admin role on the [Business Manager](https://business.facebook.com/) that owns the IG User&#039;s [Instagram Shop](https://help.instagram.com/1187859655048322). |
| [Permissions](https://developers.facebook.com/docs/apps/review/login-permissions) | [`instagram_basic`](https://developers.facebook.com/docs/facebook-login/permissions#reference-instagram_basic)  &lt;br&gt;[`instagram_content_publish`](https://developers.facebook.com/docs/permissions/reference/instagram_content_publish)  &lt;br&gt;[`pages_read_engagement`](https://developers.facebook.com/docs/facebook-login/permissions#reference-pages_read_engagement)&lt;br&gt;If the app user was granted a role on the Page via the Business Manager, you will also need one of:&lt;br&gt;&lt;br&gt;[`ads_management`](https://developers.facebook.com/docs/permissions/reference/ads_management)  &lt;br&gt;`ads_read`&lt;br&gt;&lt;br&gt;If creating containers for [product tagging](https://developers.facebook.com/documentation/instagram-platform/instagram-api-with-facebook-login/product-tagging), you will also need:&lt;br&gt;&lt;br&gt;[`catalog_management`](https://developers.facebook.com/docs/permissions/reference/catalog_management)  &lt;br&gt;[`instagram_shopping_tag_products`](https://developers.facebook.com/docs/permissions/reference/instagram_shopping_tag_products) |
| [Tasks](https://developers.facebook.com/documentation/instagram-platform/overview#tasks) | Your app user must be able to perform the `MANAGE` or `CREATE_CONTENT` tasks on the Page linked to their Instagram professional account. |

### Image Specifications

* Format: JPEG
* File size: 8 MB maximum.
* Aspect ratio: Must be within a 4:5 to 1.91:1 range
* Minimum width: 320 (will be scaled up to the minimum if necessary)
* Maximum width: 1440 (will be scaled down to the maximum if necessary)
* Height: Varies, depending on width and aspect ratio
* Color Space: sRGB. Images using other color spaces will have their color spaces converted to sRGB.

### Reel Specifications &#123;#reels-specs&#125;

The following are the specifications for Reels:

- Container: MOV or MP4 (MPEG-4 Part 14), no edit lists, moov atom at the front of the file.

- Audio codec: AAC, 48khz sample rate maximum, 1 or 2 channels (mono or stereo).

- Video codec: HEVC or H264, progressive scan, closed GOP, 4:2:0 chroma subsampling.

- Frame rate: 23-60 FPS.

- Picture size:

- Maximum columns (horizontal pixels): 1920

- Required aspect ratio is between 0.01:1 and 10:1 but we recommend 9:16 to avoid cropping or blank space.

- Video bitrate: VBR, 25Mbps maximum

- Audio bitrate: 128kbps

- Duration: 15 mins maximum, 3 seconds minimum

- File size: 300MB maximum

The following are the specifications for a Reels cover photo:

- Format: JPEG

- File size: 8MB maximum

- Color Space: sRGB. Images that use other color spaces will be converted to sRGB.

- Aspect ratio: We recommend 9:16 to avoid cropping or blank space. If the aspect ratio of the original image is not 9:16, we crop the image and use the middle most 9:16 rectangle as the cover photo for the reel.  If you share a reel to your feed, we crop the image and use the middle most 1:1 square as the cover photo for your feed post.

### Story Image Specifications

* Format: JPEG
* File size: 8 MB maximum.
* Aspect ratio: We recommended 9:16 to avoid cropping or blank space
* Color Space: sRGB. Images using other color spaces will have their color spaces converted to sRGB

### Story Video Specifications

- Container: MOV or MP4 (MPEG-4 Part 14), no edit lists, moov atom at the front of the file.

- Audio codec: AAC, 48khz sample rate maximum, 1 or 2 channels (mono or stereo).

- Video codec: HEVC or H264, progressive scan, closed GOP, 4:2:0 chroma subsampling.

- Frame rate: 23-60 FPS.

- Picture size:

- Maximum columns (horizontal pixels): 1920

- Required aspect ratio is between 0.1:1 and 10:1 but we recommend 9:16 to avoid cropping or blank space

- Video bitrate: VBR, 25Mbps maximum

- Audio bitrate: 128kbps

- Duration: 60 seconds maximum,  3 seconds minimum

- File size: 100MB maximum

### Request Syntax

#### Image Containers

```html
POST https://graph.facebook.com/v25.0/&lt;YOUR_APP_USERS_IG_USER_ID&gt;/media
?image_url=&lt;IMAGE_URL&gt;
&amp;is_carousel_item=&lt;TRUE_OR_FALSE&gt;
&amp;alt_text=&lt;IMAGE_ALTERNATIVE_TEXT&gt;
&amp;caption=&lt;IMAGE_CAPTION&gt;
&amp;location_id=&lt;LOCATION_PAGE_ID&gt;
&amp;user_tags=&lt;ARRAY_OF_USERS_FOR_TAGGING&gt;&gt;
&amp;product_tags=&lt;ARRAY_OF_PRODUCTS_FOR_TAGGING&gt;
&amp;access_token=&lt;USER_ACCESS_TOKEN&gt;
```

#### Reel Containers

##### Standard upload

```html
POST https://graph.facebook.com/v25.0/&lt;YOUR_APP_USERS_INSTAGRAM_USER_ID&gt;/media
?media_type=REELS
&amp;video_url=&lt;REEL_URL&gt;
&amp;caption=&lt;IMAGE_CAPTION&gt;
&amp;share_to_feed=&lt;TRUE_OR_FALSE&gt;
&amp;collaborators=&lt;COLLABORATOR_USERNAMES&gt;
&amp;cover_url=&lt;COVER_URL&gt;
&amp;audio_name=&lt;AUDIO_NAME&gt;
&amp;user_tags=&lt;ARRAY_OF_USERS_FOR_TAGGING&gt;&gt;
&amp;location_id=&lt;LOCATION_PAGE_ID&gt;
&amp;thumb_offset=&lt;THUMB_OFFSET&gt;
&amp;share_to_feed=&lt;TRUE_OR_FALSE&gt;
&amp;trial_params=&lt;TRIAL_PARAM&gt;
&amp;access_token=&lt;USER_ACCESS_TOKEN&gt;
```

##### Resumable upload session

```html
POST https://graph.facebook.com/v25.0/&lt;YOUR_APP_USERS_INSTAGRAM_USER_ID&gt;/media
?media_type=REELS
&amp;upload_type=resumable
&amp;caption=&lt;IMAGE_CAPTION&gt;
&amp;collaborators=&lt;COLLABORATOR_USERNAMES&gt;
&amp;cover_url=&lt;COVER_URL&gt;
&amp;audio_name=&lt;AUDIO_NAME&gt;
&amp;user_tags=&lt;ARRAY_OF_USERS_FOR_TAGGING&gt;&gt;
&amp;location_id=&lt;LOCATION_PAGE_ID&gt;
&amp;thumb_offset=&lt;THUMB_OFFSET&gt;
&amp;access_token=&lt;USER_ACCESS_TOKEN&gt;
```

On success, an `ig-container-id` and a `uri` is returned in the response, which will be used in subsequent steps, such as:

```curl
&#123;
  &quot;id&quot;: &quot;&lt;IG_CONTAINER_ID&gt;&quot;,
  &quot;uri&quot;: &quot;https://rupload.facebook.com/ig-api-upload/v25.0/&lt;IG_CONTAINER_ID&gt;&quot;
&#125;
```

#### Carousel Containers

Carousel containers only. To create carousel item containers, create image or video containers instead (reels are not supported). See [Carousel Posts](https://developers.facebook.com/documentation/instagram-platform/content-publishing#carousel-posts) for complete publishing steps.

##### Standard upload

```html
POST https://graph.facebook.com/v25.0/&lt;YOUR_APP_USERS_INSTAGRAM_USER_ID&gt;/media
?media_type=CAROUSEL
&amp;caption=&lt;IMAGE_CAPTION&gt;
&amp;share_to_feed=&lt;TRUE_OR_FALSE&gt;
&amp;collaborators=&lt;COLLABORATOR_USERNAMES&gt;
&amp;location_id=&lt;LOCATION_PAGE_ID&gt;
&amp;product_tags=&lt;ARRAY_OF_PRODUCTS_FOR_TAGGING&gt;
&amp;children=&lt;ARRAY_OF_CAROUSEL_CONTAINTER_IDS&gt;
&amp;access_token=&lt;USER_ACCESS_TOKEN&gt;
```

##### Resumable upload session

```html
POST https://graph.facebook.com/v25.0/&lt;YOUR_APP_USERS_INSTAGRAM_USER_ID&gt;/media
?media_type=VIDEO
&amp;is_carousel_item=true
&amp;upload_type=resumable
&amp;access_token=&lt;USER_ACCESS_TOKEN&gt;
```

On success, an `ig-container-id` and a `uri` is returned in the response, which will be used in subsequent steps.

#### Image Story Containers

```html
POST https://graph.facebook.com/v25.0/&lt;YOUR_APP_USERS_INSTAGRAM_USER_ID&gt;/media
?image_url=&lt;IMAGE_URL&gt;
&amp;media_type=STORIES
&amp;user_tags=&lt;ARRAY_OF_USERS_FOR_TAGGING&gt;
&amp;access_token=&lt;USER_ACCESS_TOKEN&gt;
```

#### Video Story Containers

##### Standard upload

```html
POST https://graph.facebook.com/v25.0/&lt;YOUR_APP_USERS_INSTAGRAM_USER_ID&gt;/media
?video_url=&lt;VIDEO_URL&gt;
&amp;media_type=STORIES
&amp;user_tags=&lt;ARRAY_OF_USERS_FOR_TAGGING&gt;
&amp;access_token=&lt;USER_ACCESS_TOKEN&gt;
```

##### Resumable upload session

```html
POST https://graph.facebook.com/v25.0/&lt;YOUR_APP_USERS_INSTAGRAM_USER_ID&gt;/media
?media_type=STORIES
&amp;upload_type=resumable
&amp;access_token=&lt;USER_ACCESS_TOKEN&gt;
```

On success, an Instagram container ID and a URI is returned in the response, which will be used in subsequent steps.

#### Upload a video through resumable upload protocol

Once the Instagram container ID returns from a resumable upload session call, send a `POST` request to the `https://rupload.facebook.com/ig-api-upload/`v25.0`/&lt;IG_CONTAINER_ID&gt;` endpoint.

* All media_type shares the same flow to upload the video.
* `ig-container-id` is the ID from the resumable reels, carousel and video container upload session examples above.
* `access-token` is the same one used in other steps.
* `offset` is set to the first byte being upload, generally `0`.
* `file_size` is set to the size of your file in bytes.
* `Your_file_local_path` sets to the file path of your local file, for example, if uploading a file from the **Downloads** folder on macOS, the path is **&#064;Downloads/example.mov**.

```curl
curl -X POST &quot;https://rupload.facebook.com/ig-api-upload/v25.0/&lt;IG_CONTAINER_ID&gt;&quot; \
     -H &quot;Authorization: OAuth &lt;USER_ACCESS_TOKEN&gt;&quot; \
     -H &quot;offset: 0&quot; \
     -H &quot;file_size: Your_file_size_in_bytes&quot; \
     --data-binary &quot;&#064;Your_local_file_path.extension&quot;
```

On success, you should see response like this example:

```curl
&#123;
  &quot;success&quot;:true,
  &quot;message&quot;:&quot;Upload successful. ...&quot;
&#125;
```

#### Upload a video from a hosted URL

This service can also support video upload from a hosted URL.

```curl
curl -X POST &quot;https://rupload.facebook.com/ig-api-upload/v25.0/&lt;IG_CONTAINER_ID&gt;&quot; \
     -H &quot;Authorization: OAuth &lt;USER_ACCESS_TOKEN&gt;&quot; \
     -H &quot;file_url: &lt;VIDEO_URL&gt;&quot;
```

### Path Parameters

| Placeholder | Value |
| --- | --- |
| `&lt;LATEST_API_VERSION&gt;`&lt;br&gt;The lastest API version is: v25.0&lt;br&gt; | API [version](https://developers.facebook.com/docs/graph-api/guides/versioning). |
| `&lt;YOUR_APP_USERS_INSTAGRAM_USER_ID&gt;`  &lt;br&gt;Required | App user&#039;s app-scoped user ID. |

### Query String Parameters

| Key | Placeholder | Description |
| --- | --- | --- |
| `access_token` | `&lt;USER_ACCESS_TOKEN&gt;` | Required. App user&#039;s [User](https://developers.facebook.com/documentation/facebook-login/guides/access-tokens#usertokens) access token. |
| `alt_text` | `&lt;IMAGE_ALTERNATIVE_TEXT&gt; ` | **For image posts only.** Alternative text, up to 1000 character, for an image.  Only supported on a single image or image media in a carousel.&lt;br&gt;&lt;br&gt;**Reels and stories are not supported.** |
| `audio_name` | `&lt;AUDIO_NAME&gt;` | **For Reels only.** Name of the audio of your Reels media. You can only rename once, either while creating a reel or after from the audio page. |
| `caption` | `&lt;IMAGE_CAPTION&gt;` | A caption for the image, video, or carousel. Can include hashtags (example: `#crazywildebeest`) and usernames of Instagram users (example: `&#064;natgeo`). &#064;Mentioned Instagram users receive a notification when the container is published. Maximum 2200 characters, 30 hashtags, and 20 &#064; tags.&lt;br&gt;&lt;br&gt;**Not supported on images or videos in carousels**. |
| `collaborators` | `&lt;LIST_OF_COLLABORATORS&gt;` | For Feed image, Reels and Carousels only. A list of up to 3 instagram usernames as collaborators on an ig media.&lt;br&gt;&lt;br&gt;**Not supported for Stories.** |
| `children` | `&lt;ARRAY_OF_CAROUSEL_CONTAINTER_IDS` | **Required for carousels. Applies only to carousels**. An array of up to 10 container IDs of each image and video that should appear in the published carousel. Carousels can have up to 10 total images, vidoes, or a mix of the two. |
| `cover_url` | `&lt;COVER_URL&gt;` | For Reels only. The path to an image to use as the cover image for the Reels tab. We will cURL the image using the URL that you specify so the image must be on a public server.  If you specify both `cover_url` and `thumb_offset`, we use `cover_url` and ignore `thumb_offset`.  The image must conform to the [specifications for a Reels cover photo](#reels-specs). |
| `image_url` | `&lt;IMAGE_URL&gt;` | For images only and required for images. The path to the image. We will cURL the image using the URL that you specify so the image must be on a public server. |
| `is_carousel_item` | `&lt;TRUE_OR_FALSE&gt;` | **Applies only to images and video**. Set to `true`. Indicates image or video appears in a carousel. |
| `location_id` | `&lt;LOCATION_PAGE_ID&gt;` | The ID of a [Page](https://developers.facebook.com/docs/graph-api/reference/page) associated with a location that you want to tag the image or video with.&lt;br&gt;&lt;br&gt;Use the [Pages Search API](https://developers.facebook.com/documentation/pages-api/search-pages) to search for [Pages](https://developers.facebook.com/docs/graph-api/reference/page) whose names match a search string, then parse the results to identify any Pages that have been created for a physical location. Include the `location` field in your query and verify that the Page you want to use has location data. Attempting to create a container using a Page that has no location data will fail with coded exception `INSTAGRAM_PLATFORM_API__INVALID_LOCATION_ID`.&lt;br&gt;&lt;br&gt;**Not supported on images or videos in carousels**. |
| `media_type` | `&lt;MEDIA_TYPE&gt;` | **Required for carousels, stories, and reels.** Indicates container is for a  carousel, story or reel. Value can be:&lt;br&gt;&lt;br&gt;* `CAROUSEL`&lt;br&gt;* `REELS`&lt;br&gt;* `STORIES` |
| `product_tags` | `&lt;ARRAY_OF_PRODUCTS_FOR_TAGGING&gt;` | **Required for product tagging. Applies only to images and videos**. An array of objects specifying which product tags to tag the image or video with (maximum of 5; tags and product IDs must be unique). Each object should have the following information:&lt;br&gt;&lt;br&gt;- `product_id` — **Required.** Product ID.&lt;br&gt;- `x` — **Images only.** An optional float that indicates percentage distance from left edge of the published media image. Value must be within `0.0`–`1.0` range.&lt;br&gt;- `y` — **Images only.** An optional float that indicates percentage distance from top edge of the published media image. Value must be within `0.0`–`1.0` range.&lt;br&gt;&lt;br&gt;For example:&lt;br&gt;&lt;br&gt;`[&#123;product_id:&#039;3231775643511089&#039;,x: 0.5,y: 0.8&#125;]` |
| `share_to_feed` | `&lt;TRUE_OR_FALSE&gt;` | For Reels only. When `true`, indicates that the reel can appear in both the **Feed** and **Reels** tabs. When `false`, indicates the reel can only appear in the **Reels** tab.&lt;br&gt;&lt;br&gt;**Warning:** Neither value determines whether the reel actually appears in the **Reels** tab because the reel may not meet eligibilty requirements or may not be selected by our algorithm. See [reel specifications](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-user/media#reel-specifications) for eligibility critera. |
| `thumb_offset` | `&lt;THUMB_OFFSET&gt;` | For videos and reels. Location, in milliseconds, of the video or reel frame to be used as the cover thumbnail image. The default value is `0`, which is the first frame of the video or reel.  For reels, if you specify both `cover_url` and `thumb_offset`, we use `cover_url` and ignore `thumb_offset`. |
| `upload_type` | `&lt;UPLOAD_TYPE&gt;` | An optional parameter for users want to upload video through the rupload protocol, values can be set to lowercase string value: `resumable`. |
| `user_tags` | `&lt;ARRAY_OF_USERS_FOR_TAGGING&gt;&gt;` | **Required for user tagging in images, videos, and stories.**  An array of public usernames and `x`/`y` coordinates for any public Instagram users who you want to tag in the image. Each object in the array should have the following information:&lt;br&gt;&lt;br&gt;* `username` — **Required.** Username.&lt;br&gt;* `x` — **Required for images, optional for stories. Applies only to images and stories.** A float that indicates percentage distance from left edge of the published media image. Value must be within `0.0`–`1.0` range.&lt;br&gt;* `y` — **Required for images, optional for stories. Applies only to images and stories.** A float that indicates percentage distance from top edge of the published media image. Value must be within `0.0`–`1.0` range. |
| `video_url` | `&lt;VIDEO_URL&gt;` | **Required for videos and reels. Applies only to videos and reels.** Path to the video. We cURL the video  using the passed-in URL, so it must be on a public server. |
| `trial_params` | `&lt;TRIAL_PARAM&gt;` | An optional parameter for publishing trial reels. The `media_type` must be `REELS` if this parameter is included in the request. Each object should have the following information:&lt;br&gt;&lt;br&gt;- `graduation_strategy` - **Required**. The graduation strategy specifies the conditions to graduate a reel (convert the trial reel to a reel, sharing it to followers). The value should be either `MANUAL` or `SS_PERFORMANCE`. When `MANUAL`, the trial reel can be manually graduated in the native app. When `SS_PERFORMANCE`, the trial reel will be automatically graduated if the trial reel performs well. |
| `branded_content_sponsor_ids` | `&lt;BRANDED_CONTENT_SPONSOR_IDS&gt;` | An array of Instagram user IDs of brands to tag as partners in a [partnership ads label](https://developers.facebook.com/documentation/instagram-platform/content-publishing#partnership-ads-label). Maximum 2 IDs. Use the [Business Discovery API](https://developers.facebook.com/documentation/instagram-platform/instagram-api-with-facebook-login/business-discovery) to look up a brand&#039;s ID by username. Requires `instagram_branded_content_creator` or `instagram_basic` permission.&lt;br&gt;&lt;br&gt;**Not supported on remixed media or close-friends-only posts**. |
| `is_paid_partnership` | `&lt;TRUE_OR_FALSE&gt;` | Enables the &quot;Paid partnership&quot; label on the published post. Automatically set to `true` when `branded_content_sponsor_ids` is provided. Use without `branded_content_sponsor_ids` for a label-only post. See [Partnership ads label](https://developers.facebook.com/documentation/instagram-platform/content-publishing#partnership-ads-label) for details. Available for Instagram API with Facebook Login only |
| `is_ai_generated` | `&lt;TRUE_OR_FALSE&gt;` | An optional parameter to provide a self-disclosure of AI usage in the post. Not available for carousel children. |

### Response

A JSON-formatted object containing an [IG Container](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-container) ID which you can use to [publish](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-user/media_publish) the container.

Video uploads are asynchronous, so receiving a container ID does not guarantee that the upload was successful. To verify that a video has been uploaded, request the [`status_code`](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-container#fields) field on the IG Container. If its value is `FINISHED`, the video was uploaded successfully.

```json
&#123;
  &quot;id&quot;:&quot;&lt;IG_CONTAINER_ID&gt;&quot;
&#125;
```

### Sample Request

```curl
POST graph.facebook.com/17841400008460056/media
  ?image_url=curls//www.example.com/images/bronzed-fonzes.jpg
  &amp;caption=#BronzedFonzes!
  &amp;collaborators= [‘username1’,’username2’]
  &amp;user_tags=[
    &#123;
      username:&#039;kevinhart4real&#039;,
      x: 0.5,
      y: 0.8
    &#125;,
    &#123;
      username:&#039;therock&#039;,
      x: 0.3,
      y: 0.2
    &#125;
  ]
```

### Sample Response

```json
&#123;
  &quot;id&quot;: &quot;17889455560051444&quot;
&#125;
```

## Reading

**`GET /&lt;YOUR_APP_USERS_INSTAGRAM_USER_ID&gt;/media`**

Get all [IG Media](https://developers.facebook.com/documentation/instagram-platform/reference/instagram-media) on an [IG User](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-user).

### Limitations

* Returns a maximum of 10K of the most recently created media.
* Story IG Media not supported, use the [`GET /&lt;YOUR_APP_USERS_INSTAGRAM_USER_ID&gt;/stories`](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-user/stories) endpoint instead.

### Requirements

| Type | Description |
| --- | --- |
| [Access Tokens](https://developers.facebook.com/documentation/facebook-login/guides/access-tokens#usertokens) | [User](https://developers.facebook.com/documentation/facebook-login/guides/access-tokens#usertokens) |
| [Permissions](https://developers.facebook.com/docs/apps/review/login-permissions) | [`instagram_basic`](https://developers.facebook.com/docs/facebook-login/permissions#reference-instagram_basic)  &lt;br&gt;[`pages_read_engagement`](https://developers.facebook.com/docs/facebook-login/permissions#reference-pages_read_engagement) or [`pages_show_list`](https://developers.facebook.com/docs/facebook-login/permissions#reference-pages_show_list)&lt;br&gt;&lt;br&gt;If the app user was granted a role on the Page via the Business Manager, you will also need one of:&lt;br&gt;&lt;br&gt;[`ads_management`](https://developers.facebook.com/docs/permissions/reference/ads_management)  &lt;br&gt;[`business_management`](https://developers.facebook.com/docs/permissions/reference/business_management) |

### Time-based Pagination

This endpoint supports [time-based pagination](https://developers.facebook.com/docs/graph-api/results#time). Include `since` and `until` query-string parameters with Unix timestamp or `strtotime` data values to define a time range.

### Sample Request

```curl
GET graph.facebook.com/v25.0/17841405822304914/media
```

### Sample Response

```
&#123;
  &quot;data&quot;: [
    &#123;
      &quot;id&quot;: &quot;17895695668004550&quot;
    &#125;,
    &#123;
      &quot;id&quot;: &quot;17899305451014820&quot;
    &#125;,
    &#123;
      &quot;id&quot;: &quot;17896450804038745&quot;
    &#125;,
    &#123;
      &quot;id&quot;: &quot;17881042411086627&quot;
    &#125;,
    &#123;
      &quot;id&quot;: &quot;17869102915168123&quot;
    &#125;
  ]
&#125;
```

## Updating

This operation is not supported.

## Deleting

This operation is not supported.

## See Also

* [Error Codes](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/error-codes)
