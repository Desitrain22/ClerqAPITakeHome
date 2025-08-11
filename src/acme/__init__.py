from flask import Flask, request, jsonify, render_template
from datetime import datetime
from dateutil import parser
from .client import SettlementService
import logging
import os


app = Flask(__name__)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

ACME_API_BASE_URL = os.getenv(
    "ACME_API_BASE_URL", "https://api-engine-dev.clerq.io/tech_assessment"
)

settlement_service = SettlementService()


@app.route("/")
def home():
    return render_template("index.html")


@app.route("/api")
def api_info():
    return jsonify(
        {
            "service": "ACME Settlement Service",
            "version": "1.0.0",
            "description": "Settlement calculation service for ACME Payments",
            "endpoints": {
                "settlement": "/settlement",
                "health": "/health",
                "merchants": "/merchants",
            },
        }
    )


@app.route("/merchants")
def get_merchants():
    """Get list of merchants for the dropdown"""
    try:
        response = settlement_service.api_client._make_request(
            "/merchants/", {"page": 1}
        )
        merchants = response.get("results", [])
        return jsonify(
            {"merchants": [{"id": m["id"], "name": m["name"]} for m in merchants]}
        )
    except Exception as e:
        logger.error(f"Error fetching merchants: {e}")
        return jsonify({"error": "Failed to fetch merchants"}), 500


@app.route("/health")
def health():
    """Health check endpoint"""
    try:
        settlement_service.api_client._make_request("/merchants/", {"page": 1})
        return jsonify({"status": "healthy", "acme_api": "connected"})
    except Exception as e:
        return jsonify(
            {"status": "unhealthy", "acme_api": "disconnected", "error": str(e)}
        ), 503


@app.route("/settlement")
def get_settlement():
    """
    Get settlement data for a merchant on a specific date

    Query parameters:
    - merchant_id (required): UUID of the merchant
    - date (required): Settlement date in YYYY-MM-DD format
    - timezone (optional): Timezone for the settlement calculation (default: UTC)
    """
    try:
        merchant_id = request.args.get("merchant_id")
        date_str = request.args.get("date")
        timezone_str = request.args.get("timezone", "UTC")

        if not merchant_id:
            return jsonify({"error": "merchant_id parameter is required"}), 400

        if not date_str:
            return jsonify(
                {"error": "date parameter is required (YYYY-MM-DD format)"}
            ), 400

        try:
            settlement_date = parser.parse(date_str).replace(
                hour=0, minute=0, second=0, microsecond=0
            )
        except (ValueError, parser.ParserError):
            return jsonify({"error": "Invalid date format. Use YYYY-MM-DD"}), 400

        if settlement_date.date() > datetime.now().date():
            return jsonify({"error": "Settlement date cannot be in the future"}), 400

        settlement_data = settlement_service.calculate_settlement(
            merchant_id, settlement_date, timezone_str
        )

        return jsonify(settlement_data)

    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        logger.error(f"Unexpected error in settlement endpoint: {e}")
        return jsonify({"error": "Internal server error"}), 500


@app.errorhandler(404)
def not_found(error):
    return jsonify({"error": "Endpoint not found"}), 404


@app.errorhandler(500)
def internal_error(error):
    return jsonify({"error": "Internal server error"}), 500


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
