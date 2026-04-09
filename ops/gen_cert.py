from cryptography import x509
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
import datetime
import os

KEY_FILE = "infra/nginx/certs/server.key"
CERT_FILE = "infra/nginx/certs/server.crt"

def generate_self_signed_cert():
    # Create directory if not exists
    os.makedirs("infra/nginx/certs", exist_ok=True)
    
    # 1. Generate Private Key
    key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
        backend=default_backend()
    )
    
    # Write Private Key to Disk
    with open(KEY_FILE, "wb") as f:
        f.write(key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        ))
        
    # 2. Generate Certificate
    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COUNTRY_NAME, u"FR"),
        x509.NameAttribute(NameOID.STATE_OR_PROVINCE_NAME, u"Paris"),
        x509.NameAttribute(NameOID.LOCALITY_NAME, u"Paris"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, u"Threat Hunting Corp"),
        x509.NameAttribute(NameOID.COMMON_NAME, u"localhost"),
    ])
    
    cert = x509.CertificateBuilder().subject_name(
        subject
    ).issuer_name(
        issuer
    ).public_key(
        key.public_key()
    ).serial_number(
        x509.random_serial_number()
    ).not_valid_before(
        datetime.datetime.utcnow()
    ).not_valid_after(
        # Valid for 1 year
        datetime.datetime.utcnow() + datetime.timedelta(days=365)
    ).add_extension(
        x509.SubjectAlternativeName([x509.DNSName(u"localhost")]),
        critical=False,
    # Sign with Private Key
    ).sign(key, hashes.SHA256(), default_backend())
    
    # Write Certificate to Disk
    with open(CERT_FILE, "wb") as f:
        f.write(cert.public_bytes(serialization.Encoding.PEM))
        
    print(f"✅ Generated SSL Certificate:\n  - Key: {KEY_FILE}\n  - Cert: {CERT_FILE}")

if __name__ == "__main__":
    from cryptography.hazmat.primitives import hashes
    generate_self_signed_cert()
