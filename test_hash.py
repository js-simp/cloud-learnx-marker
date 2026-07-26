import hashlib

# 1. Fill these in with your exact Sandbox details
merchant_id = "216698"
merchant_secret = "49ZJBJx8NZF4eVLTPMRdcu4ZA0mFq7Tz28QkzbxkQf0V" 

# 2. The exact order details from our HTML form
order_id = "CREDITS_100"
amount = "10000.00" # Must have exactly two decimal places
currency = "LKR"

# 3. PayHere's hashing formula
# First, hash the secret and uppercase it
hashed_secret = hashlib.md5(merchant_secret.encode('utf-8')).hexdigest().upper()

# Second, combine the strings exactly in this order
sig_string = f"{merchant_id}{order_id}{amount}{currency}{hashed_secret}"

# Third, hash the combined string and uppercase it
final_hash = hashlib.md5(sig_string.encode('utf-8')).hexdigest().upper()

print(f"Your Security Hash: {final_hash}")