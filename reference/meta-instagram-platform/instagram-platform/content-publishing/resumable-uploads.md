# Upload Video to Meta Servers



This guide shows you how to upload large video files, from local and publicly hosted content, to be published on Instagram. This is available only for apps that have implemented Facebook Login for Business.

The API allows you resume a local file upload operation after a network interruption or other transmission failure, saving time and bandwidth in the event of network failures.

### Host URLs

* `graph.facebook.com` – Create video media containers and publish and manage uploaded media
* `rupload.facebook.com` – Upload the video to Meta servers

### Endpoints

* `POST https://graph.facebook.com/<IG_USER_ID>/media?upload_type=resumable` — Initialize the upload and create a media container for the video
* `POST https://rupload.facebook.com/ig-api-upload/<IG_MEDIA_CONTAINER_ID>` — Upload the video to Meta servers
* `POST https://graph.facebook.com/<IG_USER_ID>/media_publish?creation_id=<IG_MEDIA_CONTAINER_ID>` — Publish the uploaded video
* `GET /<IG_MEDIA_CONTAINER_ID>?fields=status_code` — Check publishing eligibility and status of the video

### HTML URL encoding hints

* Some of the parameters are supported in list/dict format.
* Some characters need to be encoded into a format that can be transmitted over the Internet. For example: `user_tags=[{username:’ig_user_name’}]` is encoded to `user_tags=%5B%7Busername:ig_user_name%7D%5D` where `[` is encoded to `%5B` and `{` is encoded to `%7B`. For more conversions, please refer to the HTML URL Encoding standard.

## Create a container

To create a resumable upload session for the video, send a `POST` request to the `/<IG_USER_ID>/media` endpoint on the `graph.facebook.com` host with the following required parameters:

* `access_token` – Set to your app user's access token
* `upload_type` – Set to `resumable`
* `media_type` – Set to `REELS`, `STORIES`, or `VIDEO` (for  videos to be used in carousels)
* `is_carousel_item` – Set to `true` (for videos to be used in carousels)

### Basic example request
_Formatted for readability._

```html
curl "https://graph.facebook.com/<API_VERSION>/<IG_USER_ID>/media"
     -H "Content-Type: application/json"
     -H "Authorization: Bearer <USER_ACCESS_TOKEN>"
     -d '{
            "media_type": "<REELS_STORIES_VIDEO>"
            "upload_type=resumable"
        }'
```

#### Optional parameters for Reels

* `audio_name` – Set to the name of the audio
* `caption` – Set to the caption for the reel video
* `collaborators` – Set to a comma-separated list of up to 3 Instagram usernames of collaborators
* `cover_url` – Set to the URL to the cover image for the Reels tab
* `location_id` – Set to the ID of a Facebook Page associated with a location
* `thumb_offset` – Set to frame in the video to be used as the thumbnail
* `user_tags` – Set to an array of `username` objects for public Instagram users your app user wants to tag in the video

### Sample response

On success your app receives a JSON object with the ID and the Meta URI for the container. These two values will be used in Step 2.

```json
{
   "id": "<IG_MEDIA_CONTAINER_ID>",
   "uri": "https://rupload.facebook.com/ig-api-upload/<API_VERSION>/<IG_MEDIA_CONTAINER_ID>"
}
```

## Upload the Video

Most Graph API calls use the `graph.facebook.com` host however, calls to upload videos for Reels use `rupload.facebook.com`.

The following file sources are supported for uploaded video files:

* A file located on your computer
* A file hosted on a public facing server, such as a CDN

#### Sample request upload a local video file

With the `ig-container-id` returned from a resumable upload session call, upload the video.

* Be sure the host is `rupload.facebook.com`.
* All `media_type` shares the same flow to upload the video.
* `ig-container-id` is the ID returned from resumable upload session calls.
* `access-token` is the same one used in previous steps.
* `offset` is set to the first byte being upload, generally `0`.
* `file_size` is set to the size of your file in bytes.
* `Your_file_local_path` is set to the file path of your local file, for example, if uploading a file from, the **Downloads** folder on macOS, the path is **@Downloads/example.mov**.

```http
curl -X POST "https://rupload.facebook.com/ig-api-upload/<API_VERSION>/<IG_MEDIA_CONTAINER_ID>" \
     -H "Authorization: OAuth <ACCESS_TOKEN>" \
     -H "offset: 0" \
     -H "file_size: Your_file_size_in_bytes" \
     --data-binary "@my_video_file.mp4"
```

#### Sample request upload a public hosted video

```http
curl -X POST "https://rupload.facebook.com/ig-api-upload/<API_VERSION>/<IG_MEDIA_CONTAINER_ID>" \
     -H "Authorization: OAuth <ACCESS_TOKEN>" \
     -H "file_url: https://example_hosted_video.com"
```

#### Sample Response

```http
// Success Response Message
{
  "success":true,
  "message":"Upload successful."
}

// Failure Response Message
{
  "debug_info":{
    "retriable":false,
    "type":"ProcessingFailedError",
    "message":"{\"success\":false,\"error\":{\"message\":\"unauthorized user request\"}}"
  }
}
```

## Step 3: (Carousel Only) Create Carousel Containers

You can reuse step 1 and 2 to create multiple `ig-container-ids` with the `is_carousel_item` parameter set to `true`. Then create a Carousel Container to include all the carousel items, the carousel items can be mixed with Image and Videos.

```http
curl -X POST "https://graph.facebook.com/<API_VERSION>/<IG_USER_ID>/media" \
    -d "media_type=CAROUSEL" \
    -d "caption={caption}"\
    -d "collaborators={collaborator-usernames}" \
    -d "location_id={location-id}" \
    -d "product_tags={product-tags}" \
    -d "children=[<IG_MEDIA_CONTAINER_ID_1>,<IG_MEDIA_CONTAINER_ID_2>...]" \
    -H "Authorization: OAuth <ACCESS_TOKEN>"
```

## Step 4: Publish the Media

For Reels and Video Stories, the `<IG_MEDIA_CONTAINER_ID>` created in step 1 is used to publish the Video, and for Carousel Container, the `<IG_MEDIA_CONTAINER_ID>` created in step 3 is used to publish the Carousel Container.

```http
curl -X POST "https://graph.facebook.com/<API_VERSION>/<IG_USER_ID>/media_publish" \
    -d "creation_id=<IG_MEDIA_CONTAINER_ID>" \
    -H "Authorization: OAuth <ACCESS_TOKEN>"
```

## Step 5: Get Media Status

`graph.facebook.com` provides a `GET` endpoint to read the status of the upload, the `video_status` field contains details about the local upload process.

* The `uploading_phase` tells whether the file has been uploaded successfully, and how many bytes transferred.
* The `processing_phase` contains the details about the status of video processing after the video file is uploaded.

```http
// GET status from graph.facebook.com
curl -X GET "https://graph.facebook.com/v19.0/<IG_MEDIA_CONTAINER_ID>?fields=id,status,status_code,video_status" \
    -H "Authorization: OAuth <ACCESS_TOKEN>"
```

#### Sample Response from the `graph.facebook.com` endpoint

```http
// A successfully created ig container
{
  "id": "<IG_MEDIA_CONTAINER_ID>",
  "status": "Published: Media has been successfully published.",
  "status_code": "PUBLISHED",
  "video_status": {
    "uploading_phase": {
      "status": "complete",
      "bytes_transferred": 37006904
    },
    "processing_phase": {
      "status": "complete"
    }
  }
}

// An interrupted ig container creation, from here you can resume your upload in step 2 with offset=50002.
{
  "id": "<IG_MEDIA_CONTAINER_ID>",
  "status": "Published: Media has been successfully published.",
  "status_code": "PUBLISHED",
  "video_status": {
    "uploading_phase": {
      "status": "in_progress",
      "bytes_transferred": 50002
    },
    "processing_phase": {
      "status": "not_started"
    }
  }
}
```
