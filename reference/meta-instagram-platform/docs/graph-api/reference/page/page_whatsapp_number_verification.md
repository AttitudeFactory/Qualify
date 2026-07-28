Graph API Version

[v25.0](#)

# Page Page Whatsapp Number Verification

## Reading

You can't perform this operation on this endpoint.

## Creating

You can't perform this operation on this endpoint.

## Updating

You can update a [Page](/docs/graph-api/reference/page/) by making a POST request to [`/{page_id}/page_whatsapp_number_verification`](/docs/graph-api/reference/page/page_whatsapp_number_verification/).

### Parameters

| Parameter | Description |
| --- | --- |
|  |  |
| --- | --- |
| `verification_code`  string | The verification code which was sent to the WhatsApp number. |
| `whatsapp_number`  string | The WhatsApp number to be verified.  Required |

### Return Type

Struct {

`error_message`: string,

`verification_status`: enum,

`whatsapp_number_type`: int32,

`whatsapp_display_number`: string,

}

### Error Codes

| Error | Description |
| --- | --- |
| 200 | Permissions error |
| 100 | Invalid parameter |
| 104 | Incorrect signature |

## Deleting

You can't perform this operation on this endpoint.
