from datetime import timedelta
from decimal import Decimal
import logging
import time
import os
import random
import requests
from zoneinfo import ZoneInfo


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ACME API Configuration
ACME_API_BASE_URL = os.getenv(
    "ACME_API_BASE_URL", "https://api-engine-dev.clerq.io/tech_assessment"
)


class ACMEAPIClient:
    """Client for interacting with the ACME Payments API"""

    def __init__(self, base_url=ACME_API_BASE_URL):
        self.base_url = base_url
        self.session = requests.Session()
        # Set timeout for requests assuming the API can be slow lol
        self.timeout = 30

    def _make_request(self, endpoint, params=None, retries=3):
        """Make a request to the ACME API with error handling and retries

        params:
            endpoint (str): API endpoint to call
            params (dict): Query parameters for the request
            retries (int): Number of retry attempts on failure"""
        url = f"{self.base_url}{endpoint}"
        failed_attempts = []

        for attempt in range(retries):
            try:
                response = self.session.get(url, params=params, timeout=self.timeout)

                if response.status_code == 200:
                    result = response.json()
                    # Add failed attempts info if any occurred
                    if failed_attempts:
                        result["_request_metadata"] = {
                            "failed_attempts": failed_attempts,
                            "total_attempts": attempt + 1,
                        }
                    return result
                else:
                    failed_attempts.append(
                        {
                            "attempt": attempt + 1,
                            "status_code": response.status_code,
                            "error_type": "http_error",
                        }
                    )
                    logger.warning(
                        f"API returned status {response.status_code} for {url}"
                    )
                    if attempt == retries - 1:
                        raise Exception(
                            f"API request failed with status {response.status_code}. Failed attempts: {failed_attempts}"
                        )

            except requests.exceptions.Timeout:
                failed_attempts.append(
                    {
                        "attempt": attempt + 1,
                        "status_code": None,
                        "error_type": "timeout",
                    }
                )
                logger.warning(f"Timeout on attempt {attempt + 1} for {url}")
                if attempt == retries - 1:
                    raise Exception(
                        f"API request timed out after multiple attempts. Failed attempts: {failed_attempts}"
                    )

            except requests.exceptions.RequestException as e:
                failed_attempts.append(
                    {
                        "attempt": attempt + 1,
                        "status_code": None,
                        "error_type": "request_exception",
                        "error_message": str(e),
                    }
                )
                logger.warning(f"Request exception on attempt {attempt + 1}: {e}")
                if attempt == retries - 1:
                    raise Exception(
                        f"API request failed: {e}. Failed attempts: {failed_attempts}"
                    )

            # Wait before retry
            time.sleep(2**attempt + random.uniform(0, 1))  # (exponential backoff lol)

        raise Exception(
            f"All retry attempts failed. Failed attempts: {failed_attempts}"
        )

    def get_transactions(
        self, merchant_id=None, start_date=None, end_date=None, page=1
    ):
        """Fetch transactions with optional filtering"""
        params = {"page": page}

        if merchant_id:
            params["merchant"] = merchant_id
        if start_date:
            params["created_at__gte"] = start_date.isoformat()
        if end_date:
            params["created_at__lte"] = end_date.isoformat()

        return self._make_request("/transactions/", params)

    def get_merchant(self, merchant_id):
        """Fetch merchant details by ID"""
        return self._make_request(f"/merchants/{merchant_id}/")

    def get_orders(self, merchant_id=None, start_date=None, end_date=None, page=1):
        """Fetch orders with optional filtering"""
        params = {"page": page}

        if merchant_id:
            params["merchant"] = merchant_id
        if start_date:
            params["created_at__gte"] = start_date.isoformat()
        if end_date:
            params["created_at__lte"] = end_date.isoformat()

        return self._make_request("/orders/", params)


class SettlementService:
    """Service for calculating merchant settlements"""

    def __init__(self):
        self.api_client = ACMEAPIClient()

    def _get_settlement_period(self, settlement_date, timezone_str="UTC"):
        """Calculate the settlement period (previous business day end to settlement date end)

        Args:
            settlement_date: The settlement date (naive datetime)
            timezone_str: Timezone string (e.g., 'America/New_York', 'UTC')

        Returns:
            tuple: (period_start, period_end) as timezone-aware datetimes with ISO format
        """
        try:
            tz = ZoneInfo(timezone_str)
        except Exception as e:
            logger.warning(
                f"Invalid timezone '{timezone_str}', falling back to UTC: {e}"
            )
            tz = ZoneInfo("UTC")

        settlement_date_tz = settlement_date.replace(tzinfo=tz)

        settlement_end = settlement_date_tz.replace(
            hour=23, minute=59, second=59, microsecond=999999
        )

        # Previous business day (for now, just previous day)
        previous_day = settlement_date_tz - timedelta(days=1)
        period_start = previous_day.replace(
            hour=23, minute=59, second=59, microsecond=999999
        )

        return period_start, settlement_end

    def _fetch_all_transactions(self, merchant_id, start_date, end_date):
        """Fetch all transactions for a merchant in the given period"""
        all_transactions = []
        page = 1
        api_errors = []

        while True:
            try:
                response = self.api_client.get_transactions(
                    merchant_id=merchant_id,
                    start_date=start_date,
                    end_date=end_date,
                    page=page,
                )

                # Collect the API errors that occurred during the request
                # TODO: Break and throw in the event of 401, 403, 400, 422, 500?
                # UPDATE: Nevermind sometimes it throws 400 for fun lol
                if "_request_metadata" in response:
                    api_errors.extend(response["_request_metadata"]["failed_attempts"])

                transactions = response.get("results", [])
                all_transactions.extend(transactions)

                # Check if there are more pages
                if not response.get("next"):
                    break

                page += 1

            except Exception as e:
                logger.error(f"Error fetching transactions page {page}: {e}")
                error_msg = str(e)
                if "Failed attempts:" in error_msg:
                    api_errors.append(
                        {
                            "page": page,
                            "error": "Failed to fetch page",
                            "details": error_msg,
                        }
                    )
                else:
                    api_errors.append(
                        {"page": page, "error": "Unknown error", "details": error_msg}
                    )
                # Continue with what we have if we encounter errors
                break

        return all_transactions, api_errors

    def calculate_settlement(self, merchant_id, settlement_date, timezone_str="UTC"):
        """Calculate settlement for a merchant on a given date

        Args:
            merchant_id: UUID of the merchant
            settlement_date: The settlement date (naive datetime)
            timezone_str: Timezone string for settlement calculation (default: UTC)
        """
        api_errors = []

        try:
            try:
                merchant = self.api_client.get_merchant(
                    merchant_id
                )  # Validate the merchant exists
                if "_request_metadata" in merchant:
                    api_errors.extend(merchant["_request_metadata"]["failed_attempts"])
            except Exception as e:
                logger.error(f"Error fetching merchant {merchant_id}: {e}")
                # Extract error information from the exception message if it contains failed attempts
                error_msg = str(e)
                if "Failed attempts:" in error_msg:
                    api_errors.append(
                        {
                            "operation": "fetch_merchant",
                            "error": "Failed to fetch merchant data",
                            "details": error_msg,
                        }
                    )
                raise ValueError(f"Merchant {merchant_id} not found or API error")

            # Get settlement period with timezone handling (the full business day)
            period_start, period_end = self._get_settlement_period(
                settlement_date, timezone_str
            )

            transactions, transaction_errors = self._fetch_all_transactions(
                merchant_id, period_start, period_end
            )
            api_errors.extend(transaction_errors)

            transaction_count = 0

            purchase_total = sum(
                [
                    Decimal(str(transaction.get("amount", "0")))
                    for transaction in transactions
                    if transaction.get("type") in ("SALE", "PURCHASE")
                ]
            )
            refund_total = sum(
                [
                    Decimal(str(transaction.get("amount", "0")))
                    for transaction in transactions
                    if transaction.get("type") == "REFUND"
                ]
            )
            transaction_count = len(transactions)

            settlement_data = {
                "merchant_id": merchant_id,
                "merchant_name": merchant.get("name"),
                "settlement_date": settlement_date.date().isoformat(),
                "settlement_period": {
                    "start": period_start.isoformat(),
                    "end": period_end.isoformat(),
                },
                "settlement_amount": str(purchase_total - refund_total),
                "summary": {
                    "total_purchases": str(purchase_total),
                    "total_refunds": str(refund_total),
                    "transaction_count": transaction_count,
                    "net_settlement": str(purchase_total - refund_total),
                },
                "transactions": transactions,
            }

            # Add API errors information if any occurred
            if api_errors:
                settlement_data["api_errors"] = {
                    "total_errors": len(api_errors),
                    "error_details": api_errors,
                }

            return settlement_data

        except Exception as e:
            logger.error(f"Error calculating settlement: {e}")
            raise
