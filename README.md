# ACME Settlement Service

A Flask-based settlement service that integrates with the ACME Payments API to calculate merchant settlements.

## Overview

ACME Payments, Inc. needs a settlement service to replace their paper and pencil bookkeeping. This service integrates with ACME Payments core API to retrieve transaction data, process it, and expose a settlement endpoint to determine the settlement amount for a merchant for a given date.

## Features

- **Settlement Calculation**: Calculate net settlement amounts for merchants on specific dates
- **Error Handling**: Robust error handling for the unreliable ACME API (Including retries on 4XX/5XX, with UI documentation)
- **Retry Logic**: Automatic retries with exponential backoff for failed API calls
- **Data Validation**: Comprehensive input validation and data sanitization
- **RESTful API**: Clean REST endpoints for settlement data retrieval

## API Endpoints

### GET `/`

Returns service information and available endpoints.

### GET `/health`

Health check endpoint that verifies API connectivity.

### GET `/settlement`

Calculate settlement for a merchant on a specific date.

**Query Parameters:**

- `merchant_id` (required): UUID of the merchant
- `date` (required): Settlement date in YYYY-MM-DD format

**Response:**

```json
{
  "merchant_id": "uuid",
  "merchant_name": "Merchant Name",
  "settlement_date": "2025-08-11",
  "settlement_period": {
    "start": "2025-08-10T23:59:59.999999",
    "end": "2025-08-11T23:59:59.999999"
  },
  "settlement_amount": "150.75",
  "summary": {
    "total_purchases": "200.50",
    "total_refunds": "49.75",
    "transaction_count": 12,
    "net_settlement": "150.75"
  },
  "transactions": [...]
}
```

## Installation

The package is set up using rye. To install dependencies, run:

```bash
rye sync
```

To run the Flask application, use:

```bash
rye run flask run
```

## Configuration

The service can be configured using environment variables:

- `ACME_API_BASE_URL`: Base URL for the ACME API (default: https://api-engine-dev.clerq.io/tech_assessment)
- `API_TIMEOUT`: API request timeout in seconds (default: 30)
- `MAX_RETRIES`: Maximum number of retry attempts (default: 3)
- `HOST`: Host to bind the server to (default: 0.0.0.0)
- `PORT`: Port to run the server on (default: 5000 for flask)
- `DEBUG`: Enable debug mode (default: True)

## Usage Examples

### Get settlement for a merchant

```bash
curl "http://localhost:5000/settlement?merchant_id=123e4567-e89b-12d3-a456-426614174000&date=2025-08-11"
```

## Settlement Logic

The settlement calculation follows these rules:

1. **Settlement Period**: From the end of the previous business day through the end of business on the settlement date
2. **Transaction Types**:
   - `PURCHASE/SALE`: Positive amounts (money flows to merchant)
   - `REFUND`: Negative amounts (money flows from merchant)
3. **Net Settlement**: Sum of all purchases minus all refunds in the settlement period

## Known Issues

- The ACME API runs on old technology and occasionally returns odd responses
- Through repeated testing, the returned data from the transactions endpoint is consistent, though support for corrupt or empty fields is supported (default to 0 for transactions with no/invalid amount)
- Business day calculation currently treats all days as business days (weekend/holiday handling would need to be added production)
- Large date ranges may timeout due to API limitations

## Development notes

- Added interface, using a style/brand guide derived from the Clerq website
  - UI was mocked in MS Paint (yes, reallY) and implemented with the assistance of Claude 4
- Created requests client and seperated from API
- Timezone support -- Default to user timezone (from browser)
- Added logging / documenting for failed requests to the ACME API.
- API documentation notes 'PURCHASE' for type of transaction, but the example data uses 'SALE'. Updated to handle both.
- Introduced re-tries with getting merchants; added /merchants wrapper endpoint to flask app
