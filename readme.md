# NoteSphere Backend

[![Django](https://img.shields.io/badge/Django-6.1.3-green?logo=django)](https://www.djangoproject.com/)
[![Python](https://img.shields.io/badge/Python-3.13-blue?logo=python)](https://www.python.org/)
[![MongoDB](https://img.shields.io/badge/MongoDB-PyMongo-green?logo=mongodb)](https://www.mongodb.com/)
[![Docker](https://img.shields.io/badge/Docker-Ready-blue?logo=docker)](https://www.docker.com/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

---

## 📖 ভূমিকা (Overview)

NoteSphere একটি নোট-শেয়ারিং প্ল্যাটফর্ম যেখানে ব্যবহারকারী নিজের নোট এবং পোস্ট তৈরি করতে পারবে, অন্যদেরpublished পোস্ট দেখতে পারবে এবং অ্যাডমিন ব্যবহারকারী ও আগ্রহভিত্তিকתמשার ব্যবস্থাপনা করতে পারবেন। ব্যাকএন্ডটিতে জ(blank) gewähr নিরাপদ(authentication), রেট লিমিটিং, পাসওয়ার্ড রিসেট এবং MongoDB ইনডেক্সিং এর বন্দোবস্ত রয়েছে।

## 🚀 প্রযুক্তি স্ট্যাক (Tech Stack)

| অংশ | প্রযুক্তি |
|------|----------|
| ফ্রেমওয়ার্ক | Django 6.1.3 + Django REST Framework |
| ভাষা | Python 3.13 |
| ডাটাবেজ | MongoDB (PyMongo) + SQLite (Django 앸) |
| অথেনটিকেশন | JWT (Custom, Refresh Token Rotation) |
| API ডকুমেন্টেশন | drf-spectacular (OpenAPI/Swagger) |
| প্রোডাকশন সার্ভার | Gunicorn + Whitenoise |
| কন্টেইনারাইজেশন | Docker (মাল্টি-স্টেজ বিল্ড) |
| এনভায়রনমেন্ট | python-dotenv |

---

## ✨ মূল ফিচার্স

###орен authentication (ইনস্ট্যাশন ও অথেনটিকেশন)
- ব্যবহারকারী রেজিস্ট্রেশন এবং লগইন (ইমেইল + পাসওয়ার্ড)
- অ্যাকসেস টোকেন (শর্ট-লাইভেড) ও রিফ্রেশ টোকেন (রোটেশন সহ)
- লগআউট — রিফ্রেশ টোকেন রিভোকেশন
- বর্তমান ব্যবহারকারীর প্রোফাইল (`/auth/me/`)
- পাসওয়ার্ড রিসেট লಿಂক ইমেইলের মাধ্যমে

### 📝 নোটস (Notes)
- নিজের নোট তৈরি, পড়া, আপডেট এবং ডিলিট
- রঙ, ট্যাগ, পিন করা এবং আর্কাইভ করা নোট
- প্যাগিনেশন, সার্চ এবং সর্টিং

### 📢 পোস্টস (Posts)
- পাবলিক পোস্ট ফিড (শুধু পাবলিশ করা)
- পোস্ট তৈরি, সম্পাদনা, ডিলিট (মালিক বা অ্যাডমিন)
- ড্রাফট পোস্ট শুধুমাত্র মালিক বা অ্যাডমিন দেখতে পাবেন

### 👥 ব্যবহারকারী (Users)
- নিজস্ব প্রোফাইল দেখা এবং আপডেট
- অন্য ব্যবহারকারীর পোস্ট তালিকা (`/users/<id>/posts/`)
- ব্যবহারকারী আগ্রহভিত্তিক গ্রুপিং (`/admin/interests/`)

### ⚙️ অ্যাডমিন (Admin)
- সকল ব্যবহারকারী তালিকা, তৈরি, আপডেট এবং ডিলিট
- রোল, ইমেইল, একটিভिटी সatus পরিবর্তন

### 🔒 নিরাপত্তা
- জ(blank) gewähr নিরাপদ পাসওয়ার্ড হ্যাশিং (Django `make_password`)
- ব্রুট-ফোর্স সুরক্ষা (ইমেইল ও आईপি ভিত্তিক রেট লিমিট + লকআউট)
- অনন্য ইমেইল ও ইউজারনেম (MongoDB ইউনিক ইন্ডেক্স)
- অন্যানý ফিল্ড ব্লক (মাস অ্যাসাইনমেন্ট সুরক্ষা)
- অনুরোধ বODY সাইজ লিমিট (1 MB)
- CORS কনফিগারেশন

---

## 📁 প্রজেক্ট স্ট্রাকচার

```text
backend/configs/
├── api/                      # asosiy Django অ্যাপ
│   ├── models.py             # MongoDB ডকুমেন্ট বিল্ডার ও কনসট্যান্ট
│   ├── serializers.py        # রিকোয়েস্ট ভ্যালিডেশন ও রেসপন্স সিরিয়ালাইজার
│   ├── views.py              # API ভিউস (Auth, Users, Notes, Posts, Admin)
│   ├── urls.py               # API রউটস
│   ├── authentications.py    # JWT অথেনটিকেশন, পাসওয়ার্ড হ্যাশিং
│   ├── permissions.py        # পারমিশন ক্লাসেস
│   ├── exceptions.py         # কাস্টম এক্সেপশন হ্যান্ডলার
│   ├── admins.py             # অ্যাডমিন সার্ভিস (ইউজার ক্রিউডিলেট)
│   ├── docker_services.py    # বিসনেস লজিক (রেজিস্ট্রেশন, লগইন, রিসেট, নোট/পোস্ট)
│   ├── indexes.py            # MongoDB ইন্ডেক্স ডেফিনেশন
│   ├── tests.py              # টেস্টস
│   └── management/           # ম্যানেজমেন্ট কমান্ডস
├── configs/                  # ডিজ lançou সেটিংস
│   ├── settings.py           # ডжан Goes সেটিংস ও এনভ ভেরিয়েবল
│   ├── urls.py               # রুট URLs (api/ + ডকস)
│   ├── asgi.py / wsgi.py     # ASGI ও WSGI এন্ট্রি পয়েন্ট
├── db_connection.py          # MongoDB কনেকশন ম্যানেজার
├── manage.py                 # ডжан管理 কমান্ডলাইন
├── requirements.txt          # পাইথন ডিপেনডেন্সি
├── Dockerfile                # ডকার মাল্টি-স্টেজ বিল্ড
├── entrypoint.sh             # কন্টেইনার স্টার্ট-আপ স্ক্রিপ্ট
├── .env                      # এনভায়রনমেন্ট ভেরিয়েবল (গিটে কমিট করা নেই)
├── db.sqlite3                # ডжан ইন্টারনাল ডাটাবেজ
└── readme.md                 # এই ফাইল