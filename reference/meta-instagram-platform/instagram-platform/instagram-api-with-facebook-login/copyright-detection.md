# Copyright Detection



This guide shows you how to detect copyright violations for a video uploaded or published to Instagram using the Instagram Graph API.

We only support Instagram media created via the content publishing API for early copyright detection.

## Before you start

Before you start you will need the following:

* All requirements and limitations for accessing the Instagram Container and Instagram Media endpoints apply

### Best practices

When testing an API call, you can include the `access_token` parameter set to your access token. However, when making secure calls from your app, use the [access token class.](https://developers.facebook.com/documentation/facebook-login/guides/access-tokens#portabletokens)

## Check an uploaded video

To check the copyright status for a video that have been uploaded, but not yet published, send a `GET` request to the `/{ig-containter-id}` endpoint with the `fields` parameter set to `copyright_check_status`.

### Sample Request

```curl
curl -i -X GET "https://graph.facebook.com/v25.0/{ig-containter-id}?fields=copyright_check_status"
```

On success, your app receives a JSON response with a `copyright_check_status` object with the following key-value pairs:

* `status` set to `completed`, `error`, `in_progress`, or `not_started`
* `matches_found` set to:
    * `false` if none are detected
    * `true` if violations are detected and `author`, `content_title`, `matched_segments`, and `owner_copyright_policy` values

### Sample Responses

#### Violation found

```json
{
  "copyright_check_status": {
    "status": "complete",
    "matches_found": true
  },
  "id": "{ig-containter-id}"
}
```

#### No violation found

```json
{
  "copyright_check_status": {
      "status": "in_progress",
      "matches_found": false
  }
}
```

## Check a published video

To check the copyright status for a video that has been published, send a `GET` request to the `/{ig-media-id}` endpoint with the `fields` parameter set to `copyright_check_information`.

### Sample Request

```curl
curl -i -X GET "https://graph.facebook.com/v25.0/{ig-media-id}?fields=copyright_check_information"
```

On success, your app receives a JSON response with the `id` set to the video being checked and the `copyright_check_information` object with the following:

* `status` set to a `status` object set to `completed`, `error`, `in_progress`, or `not_started`
* `copyright_matches` set to:
    * `false` – Returned when no copyright violations are detected
    * `true` – Returned when copyright violations are detected and includes the `copyright_check_information` object that contains information about the copyright owner, policy, mitigation steps, and sections of the media that violated the copyright.

### Sample Responses

#### Violation found

```json
{
  "copyright_check_information": {
     "status": {
       "status": "complete",
       "matches_found": true
     },
     "copyright_matches": [
       {
         "content_title": "In My Feelings",
         "author": "Drake",
         "owner_copyright_policy": {
           "name": "UMG",
           "actions": [
             {
               "action": "BLOCK",
               "territories": "3",
               "geos": [
                 "Canada",
                 "India",
                 "United States of America"
               ]
             },
             {
               "action": "MUTE",
               "territories": "4",
               "geos": [
                 "Taiwan",
                 "Tanzania",
                 "Saudi Arabia",
                 "United Kingdom of Great Britain and Northern Ireland"
               ]
             }
           ]
         },
         "matched_segments": [
          {
            "start_time_in_seconds": 2.4,
            "duration_in_seconds": 5.1,
            "segment_type": "AUDIO"
          },
          {
            "start_time_in_seconds": 10.2,
            "duration_in_seconds": 4.5,
            "segment_type": "VIDEO"
          }
        ]
      }
    ]
  },
  "id": "90012800291314"
}
```

#### No violation found

```json
{
  "copyright_check_information": {
    "status": {
      "status": "complete",
      "matches_found": false
    }
  },
  "id": "{ig-media-id}"
}
```

## See also

- [Instagram Container Reference](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-container)

- [Instagram Media Reference](https://developers.facebook.com/documentation/instagram-platform/reference/instagram-media)

