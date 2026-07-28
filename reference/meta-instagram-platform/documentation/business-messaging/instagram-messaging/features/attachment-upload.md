# Upload Media for Instagram Messaging



This document shows you how to upload media to the Meta servers using the Attachment Upload API. This media can then be used in Instagram messages.

**Note:** You can upload and send an attachment in a single API call.

## Before you start

You need the following:

* The **Page ID** for the Facebook Page linked to the Instagram account your business uses to own the media to be uploaded
* A **Page access token** requested by a person who can perform the `MESSAGING` task on the Page
* Approval from the person uploading the media via Business Login for Instagram or Facebook Login for the following permissions:
    * `instagram_basic`
    * `instagram_manage_comments`
    * `instagram_manage_messages`
    * `pages_messaging`
* Your app will need **Advanced Access** for the required permissions to upload media for Pages you do not own or administer
* Either the **URL** for the media, if uploading from a URL, or the **file path** to the media, if uploading from your server
    * Media types can be `image` (which include GIFs), `video`, `audio`, or `file`
    * Media formats can be:

| Media Type | Supported Format | Supported Size Maximum |
| --- | --- | --- |
| Audio | acc, m4a, wav, mp4 | 25MB |
| Image | png, jpeg, gif | 8MB |
| Video | mp4, ogg, avi, mov, webm | 25MB |
| File | pdf | 25MB |

### Limitations

* If your app only has Standard Access to any of the required permissions, your app can only upload media for Pages you own or administer.
* These permissions allow your app to upload media but not to send messages.
* Media file names containing non-ASCII characters (such as Chinese characters) are not supported for attachment uploads.

## Upload media

You can upload media from a URL or from a server.

### From a URL

To upload media from a URL, send a `POST` request to the `/&lt;PAGE_ID&gt;/message_attachments` endpoint with the platform set as Instagram and the message attachment type set to the type of media you are uploading, `audio`, `image`, `video` or `file`. Add the URL and `is_reusable` in the payload. Set `is_reusable` to true so that the media can be used in multiple messages.

**Note:** All keys within the `message` object, such as `attachment`, `type`, and `payload` are strings.

#### Sample request
*Formatted for readability.*

```bash
curl &quot;https://graph.facebook.com/&lt;LATEST-API-VERSION&gt;/&lt;PAGE_ID&gt;/message_attachments&quot;
    -H &quot;Content-Type: application/json&quot;
    -H &quot;Authorization: Bearer &lt;PAGE_ACCESS_TOKEN&gt;&quot;
    -d &#039;&#123;
          &quot;platform&quot;:&quot;instagram&quot;,
          &quot;message&quot;:
            &#123;
              &quot;attachment&quot;:
                &#123;
                  &quot;type&quot;: &quot;&lt;MEDIA_TYPE&gt;&quot;,
                  &quot;payload&quot;:
                    &#123;
                      &quot;url&quot;: &quot;&lt;MEDIA_URL&gt;&quot;,
                      &quot;is_reusable&quot;: &quot;true&quot;,
                    &#125;,
                &#125;
            &#125;
       &#125;&#039;
```

### From a server

To upload media from a server, send a `POST` request to the `/&lt;PAGE_ID&gt;/message_attachments` endpoint with the message attachment payload containing the URL and the platform set to `instagram`. If you want to use the media in multiple messages, include the `is_reusable` set to true in the payload.

#### Sample request
*Formatted for readability. *

```bash
curl &quot;https://graph.facebook.com/&lt;LATEST-API-VERSION&gt;/&lt;PAGE_ID&gt;/message_attachments&quot;
    -H &quot;Content-Type: application/json&quot;
    -H &quot;Authorization: Bearer &lt;PAGE_ACCESS_TOKEN&gt;&quot;
    -d &#039;&#123;
          &quot;platform&quot;:&quot;instagram&quot;,
          &quot;filedata&quot;:&quot;&lt;FILE_PATH&gt;;type=&lt;PATH_TYPE&gt;&quot;,
          &quot;message&quot;:
            &#123;
              &quot;attachment&quot;:
                &#123;
                  &quot;type&quot;: &quot;&lt;MEDIA_TYPE&gt;&quot;,
                  &quot;is_reusable&quot;: &quot;true&quot;,
                &#125;
            &#125;
       &#125;&#039;
```

### Sample response

Upon success, the API returns an attachment ID. You can now include this ID in your messages.

```json
&#123;
    &quot;attachment_id&quot;: &quot;&lt;ATTACHMENT_ID&gt;&quot;
&#125;
```

## Send the media

Now that you have uploaded media, you can send it in a message.

To send a message that contains the media you uploaded, send a `POST` request to the `/&lt;PAGE_ID&gt;/messages` endpoint with the `recipient` parameter containing the Instagram-scoped ID (IGSID) and the `message` parameter containing an `attachment` object with the `type` set to `MEDIA_SHARE` and `payload.id` set to the attachment ID.

Your business must own the media to be used in the message.

#### Sample request
*Formatted for readability. *

```bash
curl &quot;https://graph.facebook.com/&lt;LATEST-API-VERSION&gt;/&lt;PAGE_ID&gt;/messages&quot;
    -H &quot;Content-Type: application/json&quot;
    -H &quot;Authorization: Bearer &lt;PAGE_ACCESS_TOKEN&gt;&quot;
    -d &#039;&#123;
          &quot;recipient&quot;:
            &#123;
              &quot;id&quot;:&quot;&lt;IGSID&gt;&quot;
            &#125;,
          &quot;message&quot;:
            &#123;
              &quot;attachment&quot;:
                &#123;
                  &quot;type&quot;: &quot;MEDIA_SHARE&quot;,
                  &quot;payload&quot;:
                    &#123;
                      &quot;attachment_id&quot;:&quot;&lt;ATTACHMENT_ID&gt;&quot;
                    &#125;
                &#125;
            &#125;
       &#125;&#039;
```

#### Sample API response &#123;#send-api-response&#125;

Upon success, the API returns a JSON response with the recipient&#039;s ID and the message&#039;s ID.

```json
&#123;
  &quot;recipient_id&quot;: &quot;&lt;IGSID&gt;&quot;,
  &quot;message_id&quot;: &quot;&lt;MESSAGE_ID&gt;&quot;
&#125;
```

## Upload and send

You can upload media and send it in a single API request.

### From a URL

To upload and send media in one request, send a `POST` request to the `/&lt;PAGE_ID&gt;/messages` endpoint with the `recipient` parameter containing the Instagram-scoped ID (IGSID) and the `message` parameter containing an `attachment` object with the `type` set to `audio`, `image`, `video` or `file` and `payload` containing the URL and `is_reusable` set to true.

#### Sample request

_Formatted for readability._

```bash
curl &quot;https://graph.facebook.com/&lt;LATEST-API-VERSION&gt;/&lt;PAGE_ID&gt;/messages&quot;
    -H &quot;Content-Type: application/json&quot;
    -H &quot;Authorization: Bearer &lt;PAGE_ACCESS_TOKEN&gt;&quot;
    -d &#039;&#123;
          &quot;recipient&quot;:
            &#123;
              &quot;id&quot;:&quot;&lt;IGSID&gt;&quot;
            &#125;,
          &quot;message&quot;:
            &#123;
              &quot;attachment&quot;:
                &#123;
                  &quot;type&quot;:&quot;&lt;MEDIA_TYPE&gt;&quot;,
                  &quot;payload&quot;:
                    &#123;
                      &quot;url&quot;:&quot;&lt;URL_TO_MEDIA&gt;&quot;
                    &#125;,
                  &quot;is_reusable&quot;: &quot;true&quot;,
                &#125;
            &#125;
       &#125;&#039;
```

### From a server

To upload and send an image, audio, file, or video from your server, send a `POST` request to the `/&lt;PAGE_ID&gt;/messages` endpoint with the `recipient` parameter containing the Instagram-scoped ID (IGSID) and the `message` parameter containing an `attachment` object with the `type` set to `AUDIO`, `IMAGE`, `VIDEO` or `FILE` and `filedata` parameter the file&#039;s location and type. The format for `filedata` values looks like `&#064;/path_on_my_server/video.mp4;type=video/mp4`.

#### Sample request

_Formatted for readability._

```bash
curl &quot;https://graph.facebook.com/&lt;LATEST-API-VERSION&gt;/&lt;PAGE_ID&gt;/messages&quot;
    -H &quot;Content-Type: application/json&quot;
    -H &quot;Authorization: Bearer &lt;PAGE_ACCESS_TOKEN&gt;&quot;
    -d &#039;&#123;
          &quot;recipient&quot;:
            &#123;
              &quot;id&quot;:&quot;&lt;IGSID&gt;&quot;
            &#125;,
          &quot;filedata&quot;:&quot;&lt;FILE_PATH&gt;;type=&lt;PATH_TYPE&gt;&quot;
          &quot;message&quot;:&#123;
            &quot;attachment&quot;:
              &#123;
                &quot;type&quot;:&quot;&lt;MEDIA_TYPE&gt;&quot;,
                &quot;is_reusable&quot;: &quot;true&quot;,
              &#125;
          &#125;
       &#125;&#039;
```

### Sample API response &#123;#upload-send-api-response&#125;

Upon success, the API returns a JSON response with the recipient ID, message ID, and attachment ID.

```json
&#123;
  &quot;recipient_id&quot;: &quot;&lt;IGSID&gt;&quot;,
  &quot;message_id&quot;: &quot;&lt;MESSAGE_ID&gt;&quot;,
  &quot;attachment_id&quot;: &quot;&lt;ATTACHMENT_ID&gt;&quot;
&#125;
```
