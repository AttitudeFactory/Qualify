# Content Publishing



This guide shows you how to publish single images, videos, reels (single media posts), or posts containing multiple images and videos (carousel posts) on Instagram professional accounts using the Instagram Platform.

**Success:** On March 24, 2025, we introduced the new `alt_text` field for image posts on the `/&lt;INSTAGRAM_PROFESSIONAL_ACCOUNT_ID&gt;/media` endpoint. Reels and stories are not supported.

## Requirements

This guide assumes you have read the [Instagram Platform Overview](https://developers.facebook.com/documentation/instagram-platform/overview) and implemented the needed components for using this API, such as a Meta login flow and a webhooks server to receive notifications.

#### Media on a public server

We cURL media used in publishing attempts, so the media must be hosted on a publicly accessible server at the time of the attempt.

#### Page Publishing Authorization

An Instagram professional account connected to a [Page](https://developers.facebook.com/documentation/instagram-platform/overview#pages) that requires [Page Publishing Authorization](https://www.facebook.com/business/m/one-sheeters/page-publishing-authorization) (PPA) cannot be published to until PPA has been completed.

It&#039;s possible that an app user may be able to perform [Tasks](https://developers.facebook.com/documentation/instagram-platform/overview#tasks) on a Page that initially does not require PPA but later requires it. In this scenario, the app user would not be able to publish content to their Instagram professional account until completing PPA. Since there&#039;s no way for you to determine if an app user&#039;s Page requires PPA, we recommend that you advise app users to preemptively complete PPA.

You will need the following:

|  | Instagram API with Instagram Login | Instagram API with Facebook Login |
| --- | --- | --- |
| **Access Levels** | * Advanced Access&lt;br&gt;* Standard Access | * Advanced Access&lt;br&gt;* Standard Access |
| **Access Tokens** | * Instagram User access token | * Facebook Page access token |
| **Host URL** | `graph.instagram.com` | `graph.facebook.com`&lt;br&gt;`rupload.facebook.com` (For resumable video uploads) |
| **Login Type** | Business Login for Instagram | Facebook Login for Business |
| [**Permissions**](https://developers.facebook.com/docs/permissions/reference#i) | * `instagram_business_basic`&lt;br&gt;* `instagram_business_content_publish` | * `instagram_basic`&lt;br&gt;* `instagram_content_publish`&lt;br&gt;* `pages_read_engagement`&lt;br&gt;&lt;br&gt;If the app user was granted a role on the [Page](https://developers.facebook.com/documentation/instagram-platform/overview#pages) connected to your app user&#039;s Instagram professional account via the Business Manager, your app will also need:&lt;br&gt;&lt;br&gt;* `ads_management`&lt;br&gt;* `ads_read` |
| **Webhooks** |  |  |

#### Endpoints

- [`/&lt;IG_ID&gt;/media`](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-user/media#creating) — Create media container and upload the media
    * `upload_type=resumable` — Create a resumbable upload session to upload large videos from an area with frequent network interruptions or other transmission failures. Only for apps that have implemented Facebook Login for Business.
- [`/&lt;IG_ID&gt;/media_publish`](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-user/media_publish#creating) — publish uploaded media using their media containers.
- [`/&lt;IG_CONTAINER_ID&gt;?fields=status_code`](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-container#reading) — check media container publishing eligibility and status.
- [`/&lt;IG_ID&gt;/content_publishing_limit`](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-user/content_publishing_limit) — check app user&#039;s current publishing rate limit usage.

* `POST https://rupload.facebook.com/ig-api-upload/&lt;IG_MEDIA_CONTAINER_ID&gt;` — Upload the video to Meta servers

* `GET /&lt;IG_MEDIA_CONTAINER_ID&gt;?fields=status_code` — Check publishing eligibility and status of the video

#### HTML URL encoding troubleshooting

* Some of the parameters are supported in list/dict format.
* Some characters need to be encoded into a format that can be transmitted over the Internet. For example: `user_tags=[&#123;username:’ig_user_name’&#125;]` is encoded to `user_tags=%5B%7Busername:ig_user_name%7D%5D` where `[` is encoded to `%5B` and `&#123;` is encoded to `%7B`. For more conversions, please refer to the HTML URL Encoding standard.

### Limitations

- JPEG is the only image format supported. Extended JPEG formats such as MPO and JPS are not supported.
- Shopping tags are not supported.
- Filters are not supported.

For additional limitations, see each endpoint&#039;s reference.

#### Rate Limit

Instagram accounts are limited to 100 API-published posts within a 24-hour moving period. Carousels count as a single post. This limit is enforced on the `POST /&lt;IG_ID&gt;/media_publish` endpoint when attempting to publish a media container. We recommend that your app also enforce the publishing rate limit, especially if your app allows app users to schedule posts to be published in the future.

To check an Instagram professional account&#039;s current rate limit usage, query the `GET /&lt;IG_ID&gt;/content_publishing_limit` endpoint.

## Create a container

In order to publish a media object, it must have a container.  To create the media container and upload a media file, send a `POST` request to the `/&lt;IG_ID&gt;/media` endpoint with the following parameters:

* `access_token` – Set to your app user&#039;s access token
* `image_url` or `video_url` – Set to the path of the image or video. We will cURL your image using the passed in URL so it must be on a public server.
* `media_type` — If the container will be for a video, set to `VIDEO`, `REELS`, or `STORIES`.
* `is_carousel_item` – If the media will be part of a carousel, set to `true`
* `upload_type` – Set to `resumable`, if creating a resumable upload session for a large video file

Visit the [Instagram User Media Endpoint Reference](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-user/media#query-string-parameters) for additional optional parameters.

#### Example Request

_Formatted for readability._

```curl
curl -X POST &quot;https://&lt;HOST_URL&gt;/&lt;LATEST_API_VERSION&gt;/&lt;IG_ID&gt;/media&quot;
     -H &quot;Content-Type: application/json&quot;
     -H &quot;Authorization: Bearer &lt;ACCESS_TOKEN&gt;&quot;
     -d &#039;&#123;
           &quot;image_url&quot;:&quot;https://www.example.com/images/bronz-fonz.jpg&quot;
         &#125;&#039;
```

On success, your app receives a JSON response with the Instagram Container ID.

```json
&#123;
  &quot;id&quot;: &quot;&lt;IG_CONTAINER_ID&gt;&quot;
&#125;
```

### Create a carousel container

To publish up to 10 images, videos, or a combination of the two, in a single post, a carousel post, you must create a carousel container. This carousel containter will contain a list of all media containers.

To create the carousel container, send a `POST` request to the `/&lt;IG_ID&gt;/media` endpoint with the following parameters:

* `media_type` — Set to `CAROUSEL`. Indicates that the container is for a carousel.
* `children` — A comma separated list of up to 10 container IDs of each image and video that should appear in the published carousel.

#### Limitations

* Carousels are limited to 10 images, videos, or a mix of the two.
* Carousel images are all cropped based on the first image in the carousel, with the default being a 1:1 aspect ratio.
* Accounts are limited to 50 published posts within a 24-hour period. Publishing a carousel counts as a single post.

#### Example Request
_Formatted for readability._

```curl
curl -X POST &quot;https://graph.instagram.com/v25.0/90010177253934/media&quot;
     -H &quot;Content-Type: application/json&quot;
     -d &#039;&#123;
           &quot;caption&quot;:&quot;Fruit%20candies&quot;
           &quot;media_type&quot;:&quot;CAROUSEL&quot;
           &quot;children&quot;:&quot;&lt;IG_CONTAINER_ID_1&gt;,&lt;IG_CONTAINER_ID_2&gt;,&lt;IG_CONTAINER_ID_3&gt;&quot;
         &#125;&#039;
```

On success, your app receives a JSON response with the Instagram Carousel Container ID.

```
&#123;
  &quot;id&quot;: &quot;&lt;IG_CAROUSEL_CONTAINER_ID&gt;&quot;
&#125;
```

## Resumable Upload Session

If you created a container for a resumable video upload in Step 1, your need to upload the video before it can be published.

Most API calls use the `graph.facebook.com` host however, calls to upload videos for Reels use `rupload.facebook.com`.

The following file sources are supported for uploaded video files:

* A file located on your computer
* A file hosted on a public facing server, such as a CDN

To start the upload session, send a `POST` request to the `/&lt;IG_MEDIA_CONTAINER_ID` endpoint on the `rupload.facebook.com` host with the following parameters:

* `access_token`
*

#### Sample request upload a local video file

With the `ig-container-id` returned from a resumable upload session call, upload the video.

* Be sure the host is `rupload.facebook.com`.
* All `media_type` shares the same flow to upload the video.
* `ig-container-id` is the ID returned from resumable upload session calls.
* `access-token` is the same one used in previous steps.
* `offset` is set to the first byte being upload, generally `0`.
* `file_size` is set to the size of your file in bytes.
* `Your_file_local_path` is set to the file path of your local file, for example, if uploading a file from, the **Downloads** folder on macOS, the path is **&#064;Downloads/example.mov**.

```curl
curl -X POST &quot;https://rupload.facebook.com/ig-api-upload/&lt;API_VERSION&gt;/&lt;IG_MEDIA_CONTAINER_ID&gt;`&quot; \
     -H &quot;Authorization: OAuth &lt;ACCESS_TOKEN&gt;&quot; \
     -H &quot;offset: 0&quot; \
     -H &quot;file_size: Your_file_size_in_bytes&quot; \
     --data-binary &quot;&#064;my_video_file.mp4&quot;
```

#### Sample request upload a public hosted video

```curl
curl -X POST &quot;https://rupload.facebook.com/ig-api-upload/&lt;API_VERSION&gt;/&lt;IG_MEDIA_CONTAINER_ID&gt;`&quot; \
     -H &quot;Authorization: OAuth &lt;ACCESS_TOKEN&gt;&quot; \
     -H &quot;file_url: https://example_hosted_video.com&quot;
```

#### Sample Response

```curl
// Success Response Message
&#123;
  &quot;success&quot;:true,
  &quot;message&quot;:&quot;Upload successful.&quot;
&#125;

// Failure Response Message
&#123;
  &quot;debug_info&quot;:&#123;
    &quot;retriable&quot;:false,
    &quot;type&quot;:&quot;ProcessingFailedError&quot;,
    &quot;message&quot;:&quot;&#123;\&quot;success\&quot;:false,\&quot;error\&quot;:&#123;\&quot;message\&quot;:\&quot;unauthorized user request\&quot;&#125;&#125;&quot;
  &#125;
&#125;
```

## Publish the container

To publish the media,

Send a `POST` request to the `/&lt;IG_ID&gt;/media_publish` endpoint with the following parameters:

* `creation_id` set to the container ID, either for a single media container or a carousel container

#### Example Request

_Formatted for readability._

```curl
curl -X POST &quot;https://&lt;HOST_URL&gt;/&lt;LATEST_API_VERSION&gt;/&lt;IG_ID&gt;/media_publish&quot;
     -H &quot;Content-Type: application/json&quot;
     -H &quot;Authorization: Bearer &lt;ACCESS_TOKEN&gt;&quot;
     -d &#039;&#123;
           &quot;creation_id&quot;:&quot;&lt;IG_CONTAINER_ID&gt;&quot;
         &#125;&#039;
```

On success, your app receives a JSON response with the Instagram Media ID.

```json
&#123;
  &quot;id&quot;: &quot;&lt;IG_MEDIA_ID&gt;&quot;
&#125;
```

## Reels posts

Reels are short-form videos that appears in the **Reels** tab of the Instagram app. To publish a reel, create a container for the video and include the `media_type=REELS` parameter along with the path to the video using the `video_url` parameter.

If you publish a reel and then request its `media_type` field, the value returned is `VIDEO`. To determine if a published video has been designated as a reel, request its `media_product_type` field instead.

You can use the [code sample on GitHub (insta_reels_publishing_api_sample)](https://github.com/fbsamples/reels_publishing_apis/tree/main/insta_reels_publishing_api_sample) to learn how to publish Reels to Instagram.

## Trial Reels posts

Trial reels are reels that are only shared to non-followers. To publish a trial reel, create a container for the video and include a valid `trial_params` parameter along with the parameters required to create reels. `trial_params` consists of the following fields:

| Field Name | Description |
| --- | --- |
| `graduation_strategy` | The graduation strategy specifies the conditions to graduate a reel (convert the trial reel to a reel, sharing it to followers). Possible values:&lt;br&gt;&lt;br&gt;- `MANUAL` — The trial reel can be manually graduated in the native app.&lt;br&gt;- `SS_PERFORMANCE` — The trial reel will be automatically graduated if the trial reel performs well. |

#### Example Request

_Formatted for readability._

```curl
curl -X POST &quot;https://graph.instagram.com/v25.0/90010177253934/media&quot;
     -H &quot;Content-Type: application/json&quot;
     -d &#039;&#123;
           &quot;media_type&quot;:&quot;REELS&quot;
           &quot;video_url&quot;:&quot;https://www.example.com/videos/bronz-fonz.mp4&quot;
           &quot;trial_params&quot;:&#123;
             “graduation_strategy”: “MANUAL”
           &#125;
         &#125;&#039;
```

## Story posts

To publish a reel, create a container for the media object and include the `media_type` parameter set to `STORIES`.

If you publish a story and then request its `media_type` field, the value will be returned as `IMAGE/VIDEO`. To determine if a published image/video is a story, request its `media_product_type` field instead.

## AI Content

To provide a self-disclosure of AI usage in the media, you can set `is_ai_generated` parameter to `true` when [creating a media container](#create-a-container). For carousels, only the carousel container needs to have the `is_ai_generated` parameter set to `true`. Setting this parameter on carousel children will result in an error. This parameter is available to both Instagram API with Facebook Login and Instagram Login.

###  Example request

```curl
curl -X POST &quot;https://graph.facebook.com/&lt;LATEST_API_VERSION&gt;/&lt;IG_USER_ID&gt;/media&quot; \
     -H &quot;Authorization: Bearer &lt;ACCESS_TOKEN&gt;&quot; \
     -d &quot;image_url=&lt;IMAGE_URL&gt;&quot; \
     -d &quot;caption=&lt;CAPTION&gt;&quot; \
     -d &quot;is_ai_generated=true&quot;
```

## Partnership ads label &#123;#partnership-ads-label&#125;

Add a partnership ads label to posts by including the `branded_content_sponsor_ids` and/or `is_paid_partnership` parameters when [creating a media container](#create-a-container). Available for Instragram API with Facebook Login only.

### Limitations

- Your app user&#039;s access token must include the `instagram_branded_content_creator` or `instagram_basic` permission.
- Sponsor accounts must be professional accounts.
- Maximum 2 sponsor tags per post.
- Not supported on close-friends-only posts or remixed media.
- This is available for Instagram API with Facebook Login only

### Parameters

| Name | Description |
| --- | --- |
| `branded_content_sponsor_ids`&lt;br&gt;&lt;br&gt;array of integers | **Optional.**  &lt;br&gt;An array of Instagram user IDs of brands to tag as partners. Maximum 2. Use the [Business Discovery API](https://developers.facebook.com/documentation/instagram-platform/instagram-api-with-facebook-login/business-discovery) to look up a brand&#039;s ID by username. |
| `is_paid_partnership`&lt;br&gt;&lt;br&gt;Boolean | **Optional.**  &lt;br&gt;Enables the &quot;Paid partnership&quot; label. Automatically set to `true` when `branded_content_sponsor_ids` is provided. Use without `branded_content_sponsor_ids` for a label-only post. |

If the brand has pre-approved the creator via the [`branded_content_tag_approval`](https://developers.facebook.com/documentation/ads-commerce/marketing-api/ad-creative/partnership-ads/post-level-permissioning#update-the-creator-approval-list) endpoint, the label shows the brand name immediately. If not, the label shows &quot;Paid partnership&quot; while pending, and the brand receives an approval notification.

After publishing, creators can use the existing [`branded_content_partner_promote`](https://developers.facebook.com/documentation/ads-commerce/marketing-api/ad-creative/partnership-ads/post-level-permissioning#allow-brand-partnerships) endpoint to give the brand permission to promote the post as a partnership ad.

### Example request

```curl
curl -X POST &quot;https://graph.facebook.com/&lt;LATEST_API_VERSION&gt;/&lt;IG_USER_ID&gt;/media&quot; \
     -H &quot;Authorization: Bearer &lt;ACCESS_TOKEN&gt;&quot; \
     -d &quot;image_url=&lt;IMAGE_URL&gt;&quot; \
     -d &quot;caption=&lt;CAPTION&gt;&quot; \
     -d &quot;branded_content_sponsor_ids=[&lt;BRAND_IG_USER_ID1&gt;, &lt;BRAND_IG_USER_ID2&gt;]&quot; \
     -d &quot;is_paid_partnership=true&quot;
```

## Troubleshooting

### Container publishing status

If you are able to create a container for a video but the `POST /&lt;IG_ID&gt;/media_publish` endpoint does not return the published media ID, you can get the container&#039;s publishing status by querying the `GET /&lt;IG_CONTAINER_ID&gt;?fields=status_code` endpoint. This endpoint will return one of the following:

- `EXPIRED` — The container was not published within 24 hours and has expired.
- `ERROR` — The container failed to complete the publishing process.
- `FINISHED` — The container and its media object are ready to be published.
- `IN_PROGRESS` — The container is still in the publishing process.
- `PUBLISHED` — The container&#039;s media object has been published.

We recommend querying a container&#039;s status once per minute, for no more than 5 minutes.

### Partnership ads label errors

| Error code | Message |
| --- | --- |
| `INSTAGRAM_PLATFORM_API__PERMISSION` | Creator is not eligible for branded content. Ensure branded content tools are enabled on the creator&#039;s account. |
| `INSTAGRAM_PLATFORM_API__INVALID_PARAM` | The specified sponsor cannot be tagged. The sponsor must be a professional account and not blocked. |
| `INSTAGRAM_PLATFORM_API__INVALID_PARAM` | Maximum number of sponsors exceeded. Limit is 2 per post. |
| `INSTAGRAM_PLATFORM_API__INVALID_PARAM` | Cannot tag yourself as sponsor. |

See the [Error Codes](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/error-codes) reference for additional errors.

## Next Steps

Now that you have published to an Instagram professional account, learn how to [moderate comments on your media](https://developers.facebook.com/documentation/instagram-platform/comment-moderation).
