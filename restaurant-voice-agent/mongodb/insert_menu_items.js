// Adds 20 dishes to MongoDB. Safe to run again: a dish that already exists (same _id) is left untouched.
//
//   mongosh "YOUR_MONGODB_URI" mongodb/insert_menu_items.js
//
// 1) DB_NAME must be the same as MONGODB_DATABASE in .env   (default: restaurant_voice)
// 2) RESTAURANT_ID must be the same as the restaurant's _id (default: demo-restaurant)
// Prices are stored in paisa (price_minor): 55000 = PKR 550.00
const DB_NAME = "restaurant_voice";
const RESTAURANT_ID = "demo-restaurant";

const rows = [
  {
    "_id": "demo-restaurant-menu-01",
    "restaurant_id": "demo-restaurant",
    "name": "Chicken Samosa",
    "description": "Crispy pastry filled with spiced chicken (6 pieces)",
    "category": "Starters",
    "price_minor": 25000,
    "available": true,
    "options": []
  },
  {
    "_id": "demo-restaurant-menu-02",
    "restaurant_id": "demo-restaurant",
    "name": "Mixed Pakora",
    "description": "Crispy fried vegetable fritters with chutney",
    "category": "Starters",
    "price_minor": 35000,
    "available": true,
    "options": [
      "extra chutney"
    ]
  },
  {
    "_id": "demo-restaurant-menu-03",
    "restaurant_id": "demo-restaurant",
    "name": "Hot and Sour Soup",
    "description": "Chicken soup with vegetables, hot and tangy",
    "category": "Starters",
    "price_minor": 45000,
    "available": true,
    "options": [
      "extra spicy",
      "mild"
    ]
  },
  {
    "_id": "demo-restaurant-menu-04",
    "restaurant_id": "demo-restaurant",
    "name": "Chicken Tikka",
    "description": "Charcoal-grilled marinated chicken (2 pieces)",
    "category": "BBQ",
    "price_minor": 55000,
    "available": true,
    "options": [
      "leg piece",
      "chest piece"
    ]
  },
  {
    "_id": "demo-restaurant-menu-05",
    "restaurant_id": "demo-restaurant",
    "name": "Seekh Kabab",
    "description": "Minced beef kababs grilled on skewers (4 pieces)",
    "category": "BBQ",
    "price_minor": 65000,
    "available": true,
    "options": [
      "extra spicy",
      "mild"
    ]
  },
  {
    "_id": "demo-restaurant-menu-06",
    "restaurant_id": "demo-restaurant",
    "name": "Chicken Malai Boti",
    "description": "Creamy, tender boneless chicken pieces from the grill",
    "category": "BBQ",
    "price_minor": 80000,
    "available": true,
    "options": []
  },
  {
    "_id": "demo-restaurant-menu-07",
    "restaurant_id": "demo-restaurant",
    "name": "Mutton Karahi",
    "description": "Mutton cooked in a wok with tomato, ginger and green chilli",
    "category": "Karahi and Handi",
    "price_minor": 220000,
    "available": true,
    "options": [
      "extra spicy",
      "mild"
    ]
  },
  {
    "_id": "demo-restaurant-menu-08",
    "restaurant_id": "demo-restaurant",
    "name": "Chicken Handi",
    "description": "Creamy chicken cooked in a clay pot",
    "category": "Karahi and Handi",
    "price_minor": 140000,
    "available": true,
    "options": [
      "extra spicy",
      "mild"
    ]
  },
  {
    "_id": "demo-restaurant-menu-09",
    "restaurant_id": "demo-restaurant",
    "name": "Chana Daal",
    "description": "Slow-cooked yellow lentils with a garlic tarka",
    "category": "Mains",
    "price_minor": 48000,
    "available": true,
    "options": [
      "extra spicy",
      "mild"
    ]
  },
  {
    "_id": "demo-restaurant-menu-10",
    "restaurant_id": "demo-restaurant",
    "name": "Chicken Biryani",
    "description": "Fragrant basmati rice layered with spiced chicken",
    "category": "Rice",
    "price_minor": 55000,
    "available": true,
    "options": [
      "extra raita",
      "less spicy"
    ]
  },
  {
    "_id": "demo-restaurant-menu-11",
    "restaurant_id": "demo-restaurant",
    "name": "Mutton Pulao",
    "description": "Tender mutton cooked with rice and whole spices",
    "category": "Rice",
    "price_minor": 75000,
    "available": true,
    "options": []
  },
  {
    "_id": "demo-restaurant-menu-12",
    "restaurant_id": "demo-restaurant",
    "name": "Zeera Rice",
    "description": "Basmati rice tempered with cumin",
    "category": "Rice",
    "price_minor": 30000,
    "available": true,
    "options": []
  },
  {
    "_id": "demo-restaurant-menu-13",
    "restaurant_id": "demo-restaurant",
    "name": "Roghni Naan",
    "description": "Soft tandoor bread brushed with ghee and sesame",
    "category": "Breads",
    "price_minor": 12000,
    "available": true,
    "options": []
  },
  {
    "_id": "demo-restaurant-menu-14",
    "restaurant_id": "demo-restaurant",
    "name": "Tandoori Roti",
    "description": "Whole-wheat bread baked in the tandoor",
    "category": "Breads",
    "price_minor": 4000,
    "available": true,
    "options": []
  },
  {
    "_id": "demo-restaurant-menu-15",
    "restaurant_id": "demo-restaurant",
    "name": "Zinger Burger",
    "description": "Crispy chicken fillet burger with sauce and lettuce",
    "category": "Fast Food",
    "price_minor": 65000,
    "available": true,
    "options": [
      "no mayo",
      "extra cheese"
    ]
  },
  {
    "_id": "demo-restaurant-menu-16",
    "restaurant_id": "demo-restaurant",
    "name": "Club Sandwich",
    "description": "Triple-decker chicken sandwich with fries",
    "category": "Fast Food",
    "price_minor": 70000,
    "available": true,
    "options": [
      "no mayo"
    ]
  },
  {
    "_id": "demo-restaurant-menu-17",
    "restaurant_id": "demo-restaurant",
    "name": "Fresh Lime Soda",
    "description": "Fresh lime with soda, sweet or salted",
    "category": "Drinks",
    "price_minor": 25000,
    "available": true,
    "options": [
      "sweet",
      "salted",
      "less ice"
    ]
  },
  {
    "_id": "demo-restaurant-menu-18",
    "restaurant_id": "demo-restaurant",
    "name": "Sweet Lassi",
    "description": "Chilled sweet yoghurt drink",
    "category": "Drinks",
    "price_minor": 30000,
    "available": true,
    "options": [
      "less sugar"
    ]
  },
  {
    "_id": "demo-restaurant-menu-19",
    "restaurant_id": "demo-restaurant",
    "name": "Gulab Jamun",
    "description": "Soft milk dumplings in sugar syrup (2 pieces)",
    "category": "Desserts",
    "price_minor": 25000,
    "available": true,
    "options": []
  },
  {
    "_id": "demo-restaurant-menu-20",
    "restaurant_id": "demo-restaurant",
    "name": "Kheer",
    "description": "Creamy rice pudding with cardamom and nuts",
    "category": "Desserts",
    "price_minor": 30000,
    "available": true,
    "options": []
  }
];

const target = db.getSiblingDB(DB_NAME);
if (!target.restaurants.findOne({ _id: RESTAURANT_ID })) {
  print("Restaurant '" + RESTAURANT_ID + "' not found in database '" + DB_NAME + "'. Start the app once (it creates it) or fix RESTAURANT_ID.");
} else {
  const now = new Date();
  const res = target.menu_items.bulkWrite(rows.map((r) => ({
    updateOne: {
      filter: { _id: r._id },
      update: { $setOnInsert: { ...r, restaurant_id: RESTAURANT_ID, created_at: now, updated_at: now } },
      upsert: true,
    },
  })));
  print("Added " + res.upsertedCount + " dishes, " + (rows.length - res.upsertedCount) + " already existed. Total dishes for this restaurant: " +
        target.menu_items.countDocuments({ restaurant_id: RESTAURANT_ID }));
}
