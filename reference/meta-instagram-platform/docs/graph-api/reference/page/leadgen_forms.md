Graph API Version

[v25.0](#)

# Page Leadgen Forms

## Reading

You can't perform this operation on this endpoint.

## Creating

You can make a POST request to `leadgen_forms` edge from the following paths:

* [`/{page_id}/leadgen_forms`](/docs/graph-api/reference/page/leadgen_forms/)

When posting to this edge, a [Page](/docs/graph-api/reference/page/) will be created.

#### Additional Errors

In addition to the errors listed below, you may receive unknown errors for `privacy_policy` if the URL is invalid or the `link_text` exceeds 70 characters.

### Permissions

If you upload an image by specifying `cover_photo` parameter, the `access_token` accompanying the request must include the `pages_manage_posts` permission.

### Parameters

| Parameter | Description |
| --- | --- |
|  |  |
| --- | --- |
| `allow_organic_lead_retrieval`  boolean | Default value: `true`  Previously, this flag controlled whether any leads submitted in a non-Ad context were retrievable. Now this flag will not be considered and it will be deprecated entirely. To control visibility of Lead Forms in a non-Ad context you should use 'block\_display\_for\_non\_targeted\_viewer' |
| `block_display_for_non_targeted_viewer`  boolean | Whether to make the organic post invisible to viewers in non-Ad context |
| `context_card`  Object | Optional context card shown as the intro page  Supports Emoji |
| `title`  string |  |
| `style`  enum {LIST\_STYLE, PARAGRAPH\_STYLE} |  |
| `content`  array<string> |  |
| `button_text`  string |  |
| `cover_photo_id`  numeric string |  |
| `cover_photo`  file | Custom cover photo for context card |
| `custom_disclaimer`  Object | Customized disclaimer including title, body content with inline links, and consent checkboxes  Supports Emoji |
| `title`  string |  |
| `body`  Object | Supports Emoji |
| `text`  string | Required |
| `url_entities`  array<JSON object> |  |
| `checkboxes`  list<Object> |  |
| `is_required`  boolean | Default value: `true` |
| `is_checked_by_default`  boolean | Default value: `false` |
| `text`  string | RequiredSupports Emoji |
| `key`  string | Supports Emoji |
| `follow_up_action_url`  URI | The final destination URL that user will go to when clicking view website button |
| `is_for_canvas`  boolean | Default value: `false`  Flag to indicate that the form is going to be used under a canvas |
| `is_lead_capture_ai_agent_enabled`  boolean | Default value: `false`  is\_lead\_capture\_ai\_agent\_enabled |
| `is_optimized_for_quality`  boolean | Default value: `false`  Flag to indicate whether the form will be optimized for quality |
| `is_phone_sms_verify_enabled`  boolean | Default value: `false`  Whether the form requires phone sms verification when user submits |
| `locale`  enum {AR\_AR, CS\_CZ, DA\_DK, DE\_DE, EL\_GR, EN\_GB, EN\_US, ES\_ES, ES\_LA, FI\_FI, FR\_FR, HE\_IL, HI\_IN, HU\_HU, ID\_ID, IT\_IT, JA\_JP, KO\_KR, NB\_NO, NL\_NL, PL\_PL, PT\_BR, PT\_PT, RO\_RO, RU\_RU, SV\_SE, TH\_TH, TR\_TR, VI\_VN, ZH\_CN, ZH\_HK, ZH\_TW} | The locale of the form. Pre-defined questions renders in this locale |
| `name`  string | The name that will help identity the form  Required |
| `privacy_policy`  Object | The url and link\_text of the privacy policy of advertiser. link\_text is limited to a maximum of 70 characters.  Supports Emoji |
| `url`  string |  |
| `link_text`  string |  |
| `question_page_custom_headline`  string | The custom headline for the question page within the form |
| `questions`  list<Object> | An array of questions of the form  Required |
| `key`  string |  |
| `label`  string |  |
| `type`  enum {CUSTOM, CITY, COMPANY\_NAME, COUNTRY, DOB, EMAIL, GENDER, FIRST\_NAME, FULL\_NAME, JOB\_TITLE, LAST\_NAME, MARITIAL\_STATUS, WHATSAPP\_NUMBER, EDUCATION\_LEVEL, WEBSITE, PHONE, PHONE\_OTP, POST\_CODE, PROVINCE, RELATIONSHIP\_STATUS, STATE, STREET\_ADDRESS, ZIP, WORK\_EMAIL, MILITARY\_STATUS, WORK\_PHONE\_NUMBER, LOCAL\_DEALER, SLIDER, STORE\_LOOKUP, STORE\_LOOKUP\_WITH\_TYPEAHEAD, DATE\_TIME, ID\_CPF, ID\_AR\_DNI, ID\_CL\_RUT, ID\_CO\_CC, ID\_EC\_CI, ID\_PE\_DNI, ID\_MX\_RFC, JOIN\_CODE, USER\_PROVIDED\_PHONE\_NUMBER, FACEBOOK\_LEAD\_ID, EMAIL\_ALIAS, MESSENGER, VIN, LICENSE\_PLATE, THREAD\_LINK, ADDRESS\_LINE\_TWO} | Required |
| `inline_context`  string |  |
| `options`  array<JSON object> |  |
| `dependent_conditional_questions`  array<JSON object> |  |
| `conditional_questions_group_id`  numeric string |  |
| `should_enforce_work_email`  boolean | Whether to enable work email enforcement. |
| `thank_you_page`  Object | Optional customized thank you page displayed post submission  Supports Emoji |
| `title`  string | Required |
| `body`  string |  |
| `short_message`  string |  |
| `button_text`  string |  |
| `button_description`  string |  |
| `business_phone_number`  phone number string |  |
| `enable_messenger`  boolean | Default value: `false` |
| `website_url`  string |  |
| `button_type`  enum {VIEW\_WEBSITE, CALL\_BUSINESS, MESSAGE\_BUSINESS, DOWNLOAD, SCHEDULE\_APPOINTMENT, VIEW\_ON\_FACEBOOK, PROMO\_CODE, NONE, WHATSAPP, P2B\_MESSENGER, BOOK\_ON\_WEBSITE} | Required |
| `country_code`  string |  |
| `gated_file`  JSON object |  |
| `id`  numeric string | id |
| `tracking_parameters`  JSON object {string : string} | Map for additional tracking parameters to include with the form's field data |
| `upload_gated_file`  file | When using Meta's marketing API to create a lead ad, you can use this field to create a gated content thank you page. This field would be the file that you'd like to use as the gated file, and the thank you page button type should be VIEW\_ON\_FACEBOOK |

### Return Type

This endpoint supports [read-after-write](/docs/graph-api/overview/#read-after-write) and will read the node represented by `id` in the return type.

Struct {

`id`: numeric string,

}

### Error Codes

| Error | Description |
| --- | --- |
| 100 | Invalid parameter |
| 192 | Invalid phone number |
| 368 | The action attempted has been deemed abusive or is otherwise disallowed |
| 80005 | There have been too many leadgen api calls to this Page account. Wait a bit and try again. For more info, please refer to https://developers.facebook.com/docs/graph-api/overview/rate-limiting. |
| 200 | Permissions error |
| 105 | The number of parameters exceeded the maximum for this operation |
| 190 | Invalid OAuth 2.0 Access Token |

## Updating

You can't perform this operation on this endpoint.

## Deleting

You can't perform this operation on this endpoint.
