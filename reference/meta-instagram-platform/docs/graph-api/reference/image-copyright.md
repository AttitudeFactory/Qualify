Graph API Version

[v25.0](#)

# Image Copyright

## Reading

Represents a copyright on an image asset.

### Example

HTTPPHP SDKJavaScript SDKAndroid SDKiOS SDK[Graph API Explorer](/tools/explorer/?method=GET&path=%7Bimage-copyright-id%7D&version=v25.0)

```
GET /v25.0/{image-copyright-id} HTTP/1.1
Host: graph.facebook.com
```

```
/* PHP SDK v5.0.0 */
/* make the API call */
try {
  // Returns a `Facebook\FacebookResponse` object
  $response = $fb->get(
    '/{image-copyright-id}',
    '{access-token}'
  );
} catch(Facebook\Exceptions\FacebookResponseException $e) {
  echo 'Graph returned an error: ' . $e->getMessage();
  exit;
} catch(Facebook\Exceptions\FacebookSDKException $e) {
  echo 'Facebook SDK returned an error: ' . $e->getMessage();
  exit;
}
$graphNode = $response->getGraphNode();
/* handle the result */
```

```
/* make the API call */
FB.api(
    "/{image-copyright-id}",
    function (response) {
      if (response && !response.error) {
        /* handle the result */
      }
    }
);
```

```
/* make the API call */
new GraphRequest(
    AccessToken.getCurrentAccessToken(),
    "/{image-copyright-id}",
    null,
    HttpMethod.GET,
    new GraphRequest.Callback() {
        public void onCompleted(GraphResponse response) {
            /* handle the result */
        }
    }
).executeAsync();
```

```
/* make the API call */
FBSDKGraphRequest *request = [[FBSDKGraphRequest alloc]
                               initWithGraphPath:@"/{image-copyright-id}"
                                      parameters:params
                                      HTTPMethod:@"GET"];
[request startWithCompletionHandler:^(FBSDKGraphRequestConnection *connection,
                                      id result,
                                      NSError *error) {
    // Handle the result
}];
```

If you want to learn how to use the Graph API, read our [Using Graph API guide](/docs/graph-api/using-graph-api/).

### Parameters

This endpoint doesn't have any parameters.

### Fields

| Field | Description |
| --- | --- |
| `id`  numeric string | The id of the object |
| `artist`  string | Artist/Photographer related the reference asset, user providedNote that the "Creator" field is used for image agencies or partners. |
| `copyright_monitoring_status`  enum | The status of the copyright reference file. It is used to determine if the match should be skipped. |
| `creation_time`  datetime | Creation time provided by TAO Server |
| `creator`  string | Creator of the reference asset, user provided |
| `custom_id`  string | Custom Id for reference asset, user provided |
| `description`  string | Description for reference asset, user provided |
| `filename`  string | Filename for reference asset, user provided |
| `image`  [Photo](https://developers.facebook.com/docs/graph-api/reference/photo/) | The underlying image asset for the copyright |
| `matches_count`  unsigned integer | The number of matches for this copyright that are displayed in Rights Manager |
| `original_content_creation_date`  datetime | Date the reference asset was created, user provided |
| `ownership_countries`  VideoCopyrightGeoGate | Countries of included or excluded ownership for the given image copyright |
| `tags`  list<string> | Tags for the reference asset |
| `title`  string | The title of the copyright, generated from the reference asset |
| `update_time`  datetime | Update time provided by TAO Server |

### Error Codes

| Error | Description |
| --- | --- |
| 368 | The action attempted has been deemed abusive or is otherwise disallowed |

## Creating

You can make a POST request to `image_copyrights` edge from the following paths:

* [`/{page_id}/image_copyrights`](/docs/graph-api/reference/page/image_copyrights/)

When posting to this edge, an [ImageCopyright](/docs/graph-api/reference/image-copyright/) will be created.

### Parameters

| Parameter | Description |
| --- | --- |
|  |  |
| --- | --- |
| `artist`  string | Artist/Photographer related to the copyright |
| `attribution_link`  string | The link to the rights holder where viewer can license the images. |
| `creator`  string | For agencies |
| `custom_id`  string | Any ID used internally by the copyright holder |
| `description`  string | Description of the copyrighted image |
| `filename`  string | Filename of the copyrighted image  Required |
| `geo_ownership`  list<enum {AC, AD, AE, AF, AG, AI, AL, AM, AN, AO, AQ, AR, AS, AT, AU, AW, AX, AZ, BA, BB, BD, BE, BF, BG, BH, BI, BJ, BL, BM, BN, BO, BQ, BR, BS, BT, BV, BW, BY, BZ, CA, CC, CD, CF, CG, CH, CI, CK, CL, CM, CN, CO, CR, CU, CV, CW, CX, CY, CZ, DE, DJ, DK, DM, DO, DZ, EC, EE, EG, EH, ER, ES, ET, FI, FJ, FK, FM, FO, FR, GA, GB, GD, GE, GF, GG, GH, GI, GL, GM, GN, GP, GQ, GR, GS, GT, GU, GW, GY, HK, HM, HN, HR, HT, HU, ID, IE, IL, IM, IN, IO, IQ, IR, IS, IT, JE, JM, JO, JP, KE, KG, KH, KI, KM, KN, KP, KR, KW, KY, KZ, LA, LB, LC, LI, LK, LR, LS, LT, LU, LV, LY, MA, MC, MD, ME, MF, MG, MH, MK, ML, MM, MN, MO, MP, MQ, MR, MS, MT, MU, MV, MW, MX, MY, MZ, NA, NC, NE, NF, NG, NI, NL, NO, NP, NR, NU, NZ, OM, PA, PE, PF, PG, PH, PK, PL, PM, PN, PR, PS, PT, PW, PY, QA, RE, RO, RS, RU, RW, SA, SB, SC, SD, SE, SG, SH, SI, SJ, SK, SL, SM, SN, SO, SR, SS, ST, SV, SX, SY, SZ, TC, TD, TF, TG, TH, TJ, TK, TL, TM, TN, TO, TP, TR, TT, TV, TW, TZ, UA, UG, UM, US, UY, UZ, VA, VC, VE, VG, VI, VN, VU, WF, WS, XK, YE, YT, ZA, ZM, ZW}> | In which territories the copyright on the image is held  Required |
| `original_content_creation_date`  int64 | When the copyrighted image was created |
| `reference_photo`  numeric string or integer | ID of the uploaded image to be protected. This must be an unpublished, temporary photo. Please refer to the [photo documentation](/docs/graph-api/reference/page/photos) on how to create unpublished, temporary photos.  Required |
| `title`  string | Title of the copyrighted image |

### Return Type

This endpoint supports [read-after-write](/docs/graph-api/overview/#read-after-write) and will read the node represented by `id` in the return type.

Struct {

`id`: numeric string,

}

### Error Codes

| Error | Description |
| --- | --- |
| 100 | Invalid parameter |

## Updating

You can update an [ImageCopyright](/docs/graph-api/reference/image-copyright/) by making a POST request to [`/{image_copyright_id}`](/docs/graph-api/reference/image-copyright/).

### Parameters

| Parameter | Description |
| --- | --- |
|  |  |
| --- | --- |
| `artist`  string | Artist/Photographer related to the copyright |
| `creator`  string | For agencies |
| `description`  string | Description of the copyrighted image |
| `geo_ownership`  list<enum {AC, AD, AE, AF, AG, AI, AL, AM, AN, AO, AQ, AR, AS, AT, AU, AW, AX, AZ, BA, BB, BD, BE, BF, BG, BH, BI, BJ, BL, BM, BN, BO, BQ, BR, BS, BT, BV, BW, BY, BZ, CA, CC, CD, CF, CG, CH, CI, CK, CL, CM, CN, CO, CR, CU, CV, CW, CX, CY, CZ, DE, DJ, DK, DM, DO, DZ, EC, EE, EG, EH, ER, ES, ET, FI, FJ, FK, FM, FO, FR, GA, GB, GD, GE, GF, GG, GH, GI, GL, GM, GN, GP, GQ, GR, GS, GT, GU, GW, GY, HK, HM, HN, HR, HT, HU, ID, IE, IL, IM, IN, IO, IQ, IR, IS, IT, JE, JM, JO, JP, KE, KG, KH, KI, KM, KN, KP, KR, KW, KY, KZ, LA, LB, LC, LI, LK, LR, LS, LT, LU, LV, LY, MA, MC, MD, ME, MF, MG, MH, MK, ML, MM, MN, MO, MP, MQ, MR, MS, MT, MU, MV, MW, MX, MY, MZ, NA, NC, NE, NF, NG, NI, NL, NO, NP, NR, NU, NZ, OM, PA, PE, PF, PG, PH, PK, PL, PM, PN, PR, PS, PT, PW, PY, QA, RE, RO, RS, RU, RW, SA, SB, SC, SD, SE, SG, SH, SI, SJ, SK, SL, SM, SN, SO, SR, SS, ST, SV, SX, SY, SZ, TC, TD, TF, TG, TH, TJ, TK, TL, TM, TN, TO, TP, TR, TT, TV, TW, TZ, UA, UG, UM, US, UY, UZ, VA, VC, VE, VG, VI, VN, VU, WF, WS, XK, YE, YT, ZA, ZM, ZW}> | In which territories the copyright on the image is held |
| `original_content_creation_date`  int64 | When the copyrighted image was created |
| `title`  string | Title of the copyrighted image |

### Return Type

This endpoint supports [read-after-write](/docs/graph-api/overview/#read-after-write) and will read the node to which you POSTed.

Struct {

`success`: bool,

}

## Deleting

You can't perform this operation on this endpoint.
